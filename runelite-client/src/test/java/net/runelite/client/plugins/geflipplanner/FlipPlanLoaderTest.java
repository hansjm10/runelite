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

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.util.Arrays;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.CLOCK;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.bytes;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.snapshot;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class FlipPlanLoaderTest
{
	@Rule
	public TemporaryFolder temporary = new TemporaryFolder();

	@Test
	public void readsLocalFile() throws Exception
	{
		Path file = temporary.newFile("plan.json").toPath();
		Files.write(file, bytes(snapshot()));
		assertEquals(4151, FlipPlanLoader.load(file, CLOCK).getCandidates().get(0).getItemId());
	}

	@Test(expected = NoSuchFileException.class)
	public void missingFileRejected() throws Exception
	{
		FlipPlanLoader.load(temporary.getRoot().toPath().resolve("missing.json"), CLOCK);
	}

	@Test(expected = IOException.class)
	public void directoryRejected() throws Exception
	{
		FlipPlanLoader.load(temporary.getRoot().toPath(), CLOCK);
	}

	@Test(expected = IOException.class)
	public void malformedFileRejected() throws Exception
	{
		Path file = temporary.newFile("plan.json").toPath();
		Files.write(file, new byte[]{'{'});
		FlipPlanLoader.load(file, CLOCK);
	}

	@Test
	public void exactLimitAcceptedAndOneExtraByteRejected() throws Exception
	{
		byte[] padded = new byte[FlipPlanParser.MAX_BYTES];
		Arrays.fill(padded, (byte) ' ');
		byte[] json = bytes(snapshot());
		System.arraycopy(json, 0, padded, 0, json.length);
		Path file = temporary.newFile("plan.json").toPath();
		Files.write(file, padded);
		assertEquals(1, FlipPlanLoader.load(file, CLOCK).getCandidates().size());
		Files.write(file, Arrays.copyOf(padded, padded.length + 1));
		try
		{
			FlipPlanLoader.load(file, CLOCK);
			fail("Expected oversize rejection");
		}
		catch (IOException expected)
		{
			assertEquals("Plan exceeds 256 KiB", expected.getMessage());
		}
	}

	@Test
	public void growingStreamCannotReadBeyondLimitPlusOne() throws Exception
	{
		int[] count = {0};
		InputStream endless = new InputStream()
		{
			@Override
			public int read()
			{
				++count[0];
				return ' ';
			}
		};
		try
		{
			FlipPlanLoader.readBounded(endless);
			fail("Expected growing stream rejection");
		}
		catch (IOException expected)
		{
			assertEquals(FlipPlanParser.MAX_BYTES + 1, count[0]);
		}
	}

	@Test
	public void smallReadsAreCollectedWithoutTruncation() throws Exception
	{
		byte[] json = bytes(snapshot());
		InputStream smallReads = new ByteArrayInputStream(json)
		{
			@Override
			public synchronized int read(byte[] target, int offset, int length)
			{
				return super.read(target, offset, Math.min(length, 7));
			}
		};
		assertEquals(json.length, FlipPlanLoader.readBounded(smallReads).length);
	}
}
