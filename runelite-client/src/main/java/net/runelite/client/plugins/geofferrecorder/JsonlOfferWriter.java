/*
 * Copyright (c) 2026, RuneLite contributors
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice, this
 *    list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright notice,
 *    this list of conditions and the following disclaimer in the documentation
 *    and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
 * ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 * (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 * LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 * SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */
package net.runelite.client.plugins.geofferrecorder;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/** One consumer, bounded memory/disk, no filesystem calls on the producer thread. */
final class JsonlOfferWriter implements AutoCloseable
{
	static final int QUEUE_CAPACITY = 256;
	static final long FILE_LIMIT = 16L * 1024 * 1024;
	static final long DIRECTORY_LIMIT = 128L * 1024 * 1024;
	static final int FILE_COUNT_LIMIT = 128;
	private static final int FAILURE_RESERVE = 1024;

	private final Path directory;
	private final String runId;
	private final Gson gson;
	private final Consumer<String> failureListener;
	private final ArrayBlockingQueue<ObservationRecord> queue;
	private final long fileLimit;
	private final long directoryLimit;
	private final int fileCountLimit;
	private final CountDownLatch finished = new CountDownLatch(1);
	private volatile boolean closing;
	private volatile String failure;

	JsonlOfferWriter(Path directory, String runId, Gson gson, Consumer<String> failureListener)
	{
		this(directory, runId, gson, failureListener, task ->
		{
			Thread thread = new Thread(task, "ge-offer-recorder");
			thread.setDaemon(true);
			thread.start();
		}, QUEUE_CAPACITY, FILE_LIMIT, DIRECTORY_LIMIT, FILE_COUNT_LIMIT);
	}

	JsonlOfferWriter(Path directory, String runId, Gson gson, Consumer<String> failureListener,
		Executor executor, int capacity, long fileLimit, long directoryLimit, int fileCountLimit)
	{
		this.directory = directory;
		this.runId = runId;
		this.gson = gson;
		this.failureListener = failureListener;
		this.queue = new ArrayBlockingQueue<>(capacity);
		this.fileLimit = fileLimit;
		this.directoryLimit = directoryLimit;
		this.fileCountLimit = fileCountLimit;
		executor.execute(this::writeLoop);
	}

	synchronized void accept(ObservationRecord record)
	{
		if (!closing && !queue.offer(record))
		{
			fail("queue_overflow");
		}
	}

	@Override
	public synchronized void close()
	{
		closing = true;
	}

	boolean awaitFinished(long timeout, TimeUnit unit) throws InterruptedException
	{
		return finished.await(timeout, unit);
	}

	private synchronized void fail(String reason)
	{
		closing = true;
		if (failure == null)
		{
			failure = reason;
			failureListener.accept(reason);
		}
	}

	private void writeLoop()
	{
		try
		{
			Files.createDirectories(directory);
			try (FileChannel channel = FileChannel.open(directory.resolve("recorder.lock"),
				StandardOpenOption.CREATE, StandardOpenOption.WRITE);
				FileLock lock = channel.tryLock())
			{
				if (lock == null)
				{
					fail("directory_in_use");
					return;
				}
				long existingBytes = 0;
				int files = 0;
				try (DirectoryStream<Path> entries = Files.newDirectoryStream(directory, "ge-offers-*.jsonl"))
				{
					for (Path path : entries)
					{
						existingBytes += Files.size(path);
						files++;
					}
				}
				long limit = Math.min(fileLimit, directoryLimit - existingBytes);
				if (files >= fileCountLimit || limit <= FAILURE_RESERVE)
				{
					fail("directory_limit");
					return;
				}
				try (OutputStream output = Files.newOutputStream(directory.resolve("ge-offers-" + runId + ".jsonl"),
					StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE))
				{
					long written = 0;
					while (!closing || !queue.isEmpty())
					{
						ObservationRecord record = queue.poll(1, TimeUnit.SECONDS);
						if (record == null)
						{
							continue;
						}
						byte[] line = line(gson.toJson(record));
						if (written + line.length > limit - FAILURE_RESERVE)
						{
							fail("file_or_directory_byte_limit");
							break;
						}
						output.write(line);
						written += line.length;
					}
					if (failure != null)
					{
						// Best effort: disk failure/crash can prevent even this marker from being saved.
						JsonObject stopped = new JsonObject();
						stopped.addProperty("schemaVersion", 1);
						stopped.addProperty("type", "recorder_failure");
						stopped.addProperty("observedAt", Instant.now().toString());
						stopped.addProperty("runId", runId);
						stopped.addProperty("reason", failure);
						output.write(line(gson.toJson(stopped)));
					}
				}
			}
		}
		catch (IOException | RuntimeException ex)
		{
			// Do not put arbitrary exception messages (which can include private paths) in records.
			fail("io_failure_" + ex.getClass().getSimpleName());
		}
		catch (InterruptedException ex)
		{
			Thread.currentThread().interrupt();
			fail("writer_interrupted");
		}
		finally
		{
			queue.clear();
			finished.countDown();
		}
	}

	private static byte[] line(String json)
	{
		return (json + "\n").getBytes(StandardCharsets.UTF_8);
	}
}
