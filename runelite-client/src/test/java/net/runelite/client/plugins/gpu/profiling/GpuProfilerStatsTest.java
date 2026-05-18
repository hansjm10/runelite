/*
 * Copyright (c) 2026, Adam <Adam@sigterm.info>
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
package net.runelite.client.plugins.gpu.profiling;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Test;

public class GpuProfilerStatsTest
{
	private static final long MS = 1_000_000L;

	@Test
	public void computesRollingStatsAndPercentiles()
	{
		GpuProfilerFrame[] history = new GpuProfilerFrame[4];
		for (int i = 0; i < history.length; ++i)
		{
			history[i] = frame(i + 1);
		}
		history[0].addCpuNanos(GpuProfilerPhase.FRAME, 1 * MS);
		history[1].addCpuNanos(GpuProfilerPhase.FRAME, 2 * MS);
		history[2].addCpuNanos(GpuProfilerPhase.FRAME, 3 * MS);
		history[3].addCpuNanos(GpuProfilerPhase.FRAME, 100 * MS);

		GpuProfilerSnapshot snapshot = GpuProfilerStats.snapshot(true, "renderer", "version", true, true, true, history);
		GpuProfilerSnapshot.PhaseStats stats = snapshot.getCpuStats(GpuProfilerPhase.FRAME);

		assertEquals(4, stats.getSampleCount());
		assertEquals(100 * MS, stats.getLatestNanos());
		assertEquals(26.5d * MS, stats.getAverageNanos(), 0.001d);
		assertEquals(100 * MS, stats.getP95Nanos());
		assertEquals(100 * MS, stats.getMaxNanos());
	}

	@Test
	public void preservesUnavailableGpuResults()
	{
		GpuProfilerFrame[] history = {frame(1)};
		history[0].addCpuNanos(GpuProfilerPhase.SCENE_SETUP, 2 * MS);

		GpuProfilerSnapshot snapshot = GpuProfilerStats.snapshot(true, "renderer", "version", true, true, true, history);

		assertTrue(snapshot.getCpuStats(GpuProfilerPhase.SCENE_SETUP).isAvailable());
		assertFalse(snapshot.getGpuStats(GpuProfilerPhase.SCENE_SETUP).isAvailable());
	}

	@Test
	public void formatsCsvWithStableFieldsAndBlankMissingGpuDurations()
	{
		GpuProfilerFrame[] history = {frame(7)};
		history[0].addCpuNanos(GpuProfilerPhase.SCENE_SETUP, 1_500_000L);
		history[0].setGpuNanos(GpuProfilerPhase.SCENE_SETUP, 2_500_000L);
		history[0].incrementCounter(GpuProfilerCounter.OPAQUE_ZONE_DRAWS, 3);

		String csv = GpuProfilerExport.toCsv("Renderer, Inc.", "4.1 \"Driver\"", history);
		String[] lines = csv.split("\n");

		assertTrue(lines[0].contains("cpu_scene_setup_ms,gpu_scene_setup_ms"));
		assertTrue(lines[0].contains("gpu_swap_buffers_ms"));
		assertTrue(lines[1].contains("\"Renderer, Inc.\""));
		assertTrue(lines[1].contains("\"4.1 \"\"Driver\"\"\""));
		assertTrue(lines[1].contains(",3,"));
		assertTrue(lines[1].contains(",1.500,2.500,"));
		assertTrue(lines[1].endsWith(","));
	}

	@Test
	public void resetClearsSamples()
	{
		GpuProfiler profiler = new GpuProfiler();
		profiler.start(null, "renderer", "version", false);
		profiler.beginFrame(765, 503, 765, 503, 765, 503, false, 50, 3, "MSAA_2", 1, "HYBRID", true, "OFF", 60, 0, 100);
		profiler.endFrame();

		assertEquals(1, profiler.snapshot().getSampleCount());

		profiler.reset();

		assertEquals(0, profiler.snapshot().getSampleCount());
	}

	@Test
	public void historyIsBounded()
	{
		GpuProfiler profiler = new GpuProfiler();
		profiler.start(null, "renderer", "version", false);
		for (int i = 0; i < 305; ++i)
		{
			profiler.beginFrame(765, 503, 765, 503, 765, 503, false, 50, 3, "MSAA_2", 1, "HYBRID", true, "OFF", 60, 0, 100);
			profiler.endFrame();
		}

		GpuProfilerSnapshot snapshot = profiler.snapshot();
		assertEquals(300, snapshot.getSampleCount());
		assertEquals(304, snapshot.getLatestFrameId());
	}

	@Test
	public void readsAvailableGpuQueriesAfterRingLatency()
	{
		FakeGl gl = new FakeGl();
		gl.available = true;
		gl.queryResult = 9 * MS;
		GpuProfiler profiler = new GpuProfiler(gl);
		profiler.start("renderer", "version", true, false, false);

		recordFrame(profiler, true);
		for (int i = 0; i < 8; ++i)
		{
			recordFrame(profiler, false);
		}

		GpuProfilerSnapshot snapshot = profiler.snapshot();
		assertEquals(1, snapshot.getGpuStats(GpuProfilerPhase.SCENE_SETUP).getSampleCount());
		assertEquals(9 * MS, snapshot.getGpuStats(GpuProfilerPhase.SCENE_SETUP).getLatestNanos());
		assertEquals(1, gl.resultCalls);
	}

	@Test
	public void dropsUnavailableGpuQueriesWithoutBlockingResultRead()
	{
		FakeGl gl = new FakeGl();
		gl.available = false;
		GpuProfiler profiler = new GpuProfiler(gl);
		profiler.start("renderer", "version", true, false, false);

		recordFrame(profiler, true);
		for (int i = 0; i < 8; ++i)
		{
			recordFrame(profiler, false);
		}

		GpuProfilerSnapshot snapshot = profiler.snapshot();
		assertFalse(snapshot.getGpuStats(GpuProfilerPhase.SCENE_SETUP).isAvailable());
		assertEquals(1, snapshot.getUnavailableQueryCount());
		assertEquals(1, snapshot.getDroppedQueryCount());
		assertEquals(0, gl.resultCalls);
		assertEquals(1, gl.deleteCalls);
	}

	@Test
	public void keepsCpuTimingsWhenGpuQueryFails()
	{
		FakeGl gl = new FakeGl();
		gl.throwOnBegin = true;
		GpuProfiler profiler = new GpuProfiler(gl);
		profiler.start("renderer", "version", true, false, false);

		recordFrame(profiler, true);

		GpuProfilerSnapshot snapshot = profiler.snapshot();
		assertFalse(snapshot.isTimerQueriesSupported());
		assertTrue(snapshot.getCpuStats(GpuProfilerPhase.SCENE_SETUP).isAvailable());
	}

	@Test
	public void disablesTimerQueriesWhenQueryAllocationFails()
	{
		FakeGl gl = new FakeGl();
		gl.throwOnGen = true;
		GpuProfiler profiler = new GpuProfiler(gl);
		profiler.start("renderer", "version", true, false, false);

		recordFrame(profiler, true);

		GpuProfilerSnapshot snapshot = profiler.snapshot();
		assertFalse(snapshot.isTimerQueriesSupported());
		assertTrue(snapshot.getCpuStats(GpuProfilerPhase.SCENE_SETUP).isAvailable());
	}

	@Test
	public void emitsDebugGroupsWithoutTimerQueries()
	{
		FakeGl gl = new FakeGl();
		GpuProfiler profiler = new GpuProfiler(gl);
		profiler.start("renderer", "version", false, true, true);

		recordFrame(profiler, true);

		assertEquals(1, gl.pushDebugGroupCalls);
		assertEquals(1, gl.popDebugGroupCalls);
	}

	private static GpuProfilerFrame frame(long frameId)
	{
		GpuProfilerFrame frame = new GpuProfilerFrame();
		frame.setMetadata(10, frameId, 20, 765, 503, 765, 503, 765, 503, false, 50, 3,
			"MSAA_2", 1, "HYBRID", true, "OFF", 60, 0, 100, true, true, true);
		return frame;
	}

	private static void recordFrame(GpuProfiler profiler, boolean sceneSetup)
	{
		profiler.beginFrame(765, 503, 765, 503, 765, 503, false, 50, 3, "MSAA_2", 1, "HYBRID", true, "OFF", 60, 0, 100);
		if (sceneSetup)
		{
			profiler.beginPhase(GpuProfilerPhase.SCENE_SETUP);
			profiler.endPhase(GpuProfilerPhase.SCENE_SETUP);
		}
		profiler.endFrame();
	}

	private static final class FakeGl implements GpuProfilerGl
	{
		private int nextQuery = 1;
		private boolean available;
		private boolean throwOnGen;
		private boolean throwOnBegin;
		private long queryResult;
		private int resultCalls;
		private int deleteCalls;
		private int pushDebugGroupCalls;
		private int popDebugGroupCalls;

		@Override
		public int genQuery()
		{
			if (throwOnGen)
			{
				throw new RuntimeException("allocation failed");
			}
			return nextQuery++;
		}

		@Override
		public void deleteQuery(int query)
		{
			++deleteCalls;
		}

		@Override
		public void beginTimerQuery(int query)
		{
			if (throwOnBegin)
			{
				throw new RuntimeException("query failed");
			}
		}

		@Override
		public void endTimerQuery()
		{
		}

		@Override
		public boolean isQueryResultAvailable(int query)
		{
			return available;
		}

		@Override
		public long getQueryResult(int query)
		{
			++resultCalls;
			return queryResult;
		}

		@Override
		public void pushDebugGroup(int id, String label)
		{
			++pushDebugGroupCalls;
		}

		@Override
		public void popDebugGroup()
		{
			++popDebugGroupCalls;
		}

		@Override
		public void objectLabel(int identifier, int object, String label)
		{
		}
	}
}
