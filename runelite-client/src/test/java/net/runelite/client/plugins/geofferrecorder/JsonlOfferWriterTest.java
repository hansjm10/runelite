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
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class JsonlOfferWriterTest
{
	@Rule
	public TemporaryFolder temporary = new TemporaryFolder();

	private final Gson gson = new Gson();
	private final List<Runnable> tasks = new ArrayList<>();
	private final List<String> failures = new ArrayList<>();

	@Test
	public void orderedJsonlAndCloseDrainWithoutProducerIo() throws Exception
	{
		Path directory = temporary.getRoot().toPath().resolve("records");
		JsonlOfferWriter writer = writer(directory, 32, 16_384, 32_768, 10);
		for (int i = 1; i <= 10; i++)
		{
			writer.accept(record(i));
		}
		writer.close();
		assertFalse(Files.exists(directory));
		Thread thread = new Thread(tasks.get(0), "test-offer-writer");
		thread.start();
		assertTrue(writer.awaitFinished(5, TimeUnit.SECONDS));
		List<JsonObject> records = records(directory);
		assertEquals(10, records.size());
		for (int i = 0; i < records.size(); i++)
		{
			assertEquals(i + 1, records.get(i).get("sequence").getAsInt());
		}
		assertTrue(failures.isEmpty());
	}

	@Test
	public void overflowStopsRatherThanSilentlyDroppingAndResuming() throws Exception
	{
		Path directory = temporary.getRoot().toPath();
		JsonlOfferWriter writer = writer(directory, 2, 16_384, 32_768, 10);
		writer.accept(record(1));
		writer.accept(record(2));
		writer.accept(record(3));
		writer.accept(record(4));
		tasks.get(0).run();
		assertEquals(java.util.Collections.singletonList("queue_overflow"), failures);
		List<JsonObject> records = records(directory);
		assertEquals(3, records.size());
		assertEquals(2, records.get(1).get("sequence").getAsInt());
		assertEquals("recorder_failure", records.get(2).get("type").getAsString());
	}

	@Test
	public void byteLimitReservesRoomForExplicitFailure() throws Exception
	{
		Path directory = temporary.getRoot().toPath();
		JsonlOfferWriter writer = writer(directory, 64, 2048, 32_768, 10);
		for (int i = 0; i < 30; i++)
		{
			writer.accept(record(i));
		}
		writer.close();
		tasks.get(0).run();
		assertEquals(java.util.Collections.singletonList("file_or_directory_byte_limit"), failures);
		assertTrue(Files.size(directory.resolve("ge-offers-test.jsonl")) <= 2048);
		List<JsonObject> records = records(directory);
		assertEquals("recorder_failure", records.get(records.size() - 1).get("type").getAsString());
	}

	@Test
	public void directoryCountAndByteLimitsPreserveExistingData() throws Exception
	{
		Path directory = temporary.getRoot().toPath();
		Path old = directory.resolve("ge-offers-old.jsonl");
		Files.write(old, new byte[1500]);
		JsonlOfferWriter writer = writer(directory, 2, 4096, 8192, 1);
		writer.close();
		tasks.get(0).run();
		assertEquals("directory_limit", failures.get(0));
		assertEquals(1500, Files.size(old));
		assertFalse(Files.exists(directory.resolve("ge-offers-test.jsonl")));

		JsonlOfferWriter second = writer(directory, 2, 4096, 2000, 10);
		second.close();
		tasks.get(1).run();
		assertEquals("directory_limit", failures.get(1));
	}

	@Test
	public void ioAndLockFailuresAreReported() throws Exception
	{
		Path notDirectory = temporary.newFile().toPath();
		JsonlOfferWriter writer = writer(notDirectory, 2, 4096, 8192, 10);
		writer.close();
		tasks.get(0).run();
		assertTrue(failures.get(0).startsWith("io_failure_"));
		assertTrue(writer.awaitFinished(1, TimeUnit.SECONDS));

		Path directory = temporary.newFolder().toPath();
		try (FileChannel channel = FileChannel.open(directory.resolve("recorder.lock"), StandardOpenOption.CREATE, StandardOpenOption.WRITE);
			FileLock lock = channel.lock())
		{
			assertTrue(lock.isValid());
			JsonlOfferWriter second = writer(directory, 2, 4096, 8192, 10);
			second.close();
			tasks.get(1).run();
			assertEquals("io_failure_OverlappingFileLockException", failures.get(1));
			assertFalse(Files.exists(directory.resolve("ge-offers-test.jsonl")));
		}
	}

	private JsonlOfferWriter writer(Path directory, int capacity, long fileLimit, long directoryLimit, int fileCountLimit)
	{
		return new JsonlOfferWriter(directory, "test", gson, failures::add, tasks::add,
			capacity, fileLimit, directoryLimit, fileCountLimit);
	}

	private ObservationRecord record(long sequence)
	{
		return new ObservationRecord("heartbeat", "2026-01-01T00:00:00Z", "test", sequence,
			null, "test", null, null, null, null, null, null);
	}

	private List<JsonObject> records(Path directory) throws Exception
	{
		return Files.readAllLines(directory.resolve("ge-offers-test.jsonl"), StandardCharsets.UTF_8).stream()
			.map(line -> gson.fromJson(line, JsonObject.class)).collect(Collectors.toList());
	}
}
