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
package net.runelite.client.plugins.geflipplanner;

import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.time.Clock;
import java.util.Arrays;

final class FlipPlanLoader
{
	private FlipPlanLoader()
	{
	}

	static FlipPlan load(Path path, Clock clock) throws IOException
	{
		BasicFileAttributes attributes = Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
		if (!attributes.isRegularFile())
		{
			throw new IOException("Plan must be a regular local file");
		}
		try (InputStream input = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS))
		{
			return FlipPlanParser.parse(readBounded(input), clock);
		}
	}

	static byte[] readBounded(InputStream input) throws IOException
	{
		// Do not trust a pre-read file size: the producer may replace or grow the file.
		// Read at most one byte beyond the limit, even from an endlessly growing source.
		byte[] bytes = new byte[FlipPlanParser.MAX_BYTES + 1];
		int count = 0;
		while (count < bytes.length)
		{
			if (Thread.currentThread().isInterrupted())
			{
				throw new InterruptedIOException("Plan loading cancelled");
			}
			int read = input.read(bytes, count, bytes.length - count);
			if (read == -1)
			{
				return Arrays.copyOf(bytes, count);
			}
			count += read;
		}
		throw new IOException("Plan exceeds 256 KiB");
	}
}
