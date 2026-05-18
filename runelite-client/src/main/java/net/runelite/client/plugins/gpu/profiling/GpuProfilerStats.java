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
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 * SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */
package net.runelite.client.plugins.gpu.profiling;

import java.util.Arrays;

public final class GpuProfilerStats
{
	private GpuProfilerStats()
	{
	}

	public static GpuProfilerSnapshot snapshot(
		boolean enabled,
		String renderer,
		String glVersion,
		boolean timerQueriesSupported,
		boolean debugMarkersSupported,
		boolean debugMarkersEnabled,
		GpuProfilerFrame[] history)
	{
		int sampleCount = 0;
		long latestFrameId = -1;
		int maxQueryLatencyFrames = -1;
		long unavailableQueryCount = 0;
		long droppedQueryCount = 0;
		GpuProfilerFrame latestFrame = null;

		for (GpuProfilerFrame frame : history)
		{
			if (!frame.isValid())
			{
				continue;
			}

			++sampleCount;
			if (frame.getFrameId() > latestFrameId)
			{
				latestFrameId = frame.getFrameId();
				latestFrame = frame;
			}
			maxQueryLatencyFrames = Math.max(maxQueryLatencyFrames, frame.getQueryLatencyFrames());
			unavailableQueryCount += frame.getUnavailableQueryCount();
			droppedQueryCount += frame.getDroppedQueryCount();
		}

		GpuProfilerSnapshot.PhaseStats[] cpuStats = new GpuProfilerSnapshot.PhaseStats[GpuProfilerPhase.VALUES.length];
		GpuProfilerSnapshot.PhaseStats[] gpuStats = new GpuProfilerSnapshot.PhaseStats[GpuProfilerPhase.VALUES.length];
		long[] values = new long[history.length];
		for (GpuProfilerPhase phase : GpuProfilerPhase.VALUES)
		{
			cpuStats[phase.ordinal()] = phaseStats(phase, history, values, true);
			gpuStats[phase.ordinal()] = phaseStats(phase, history, values, false);
		}

		GpuProfilerSnapshot.CounterStats[] counterStats = new GpuProfilerSnapshot.CounterStats[GpuProfilerCounter.VALUES.length];
		for (GpuProfilerCounter counter : GpuProfilerCounter.VALUES)
		{
			counterStats[counter.ordinal()] = counterStats(counter, history, sampleCount, latestFrame);
		}

		return new GpuProfilerSnapshot(
			enabled,
			renderer,
			glVersion,
			timerQueriesSupported,
			debugMarkersSupported,
			debugMarkersEnabled,
			sampleCount,
			latestFrameId,
			maxQueryLatencyFrames,
			unavailableQueryCount,
			droppedQueryCount,
			cpuStats,
			gpuStats,
			counterStats);
	}

	private static GpuProfilerSnapshot.PhaseStats phaseStats(
		GpuProfilerPhase phase,
		GpuProfilerFrame[] history,
		long[] values,
		boolean cpu)
	{
		int count = 0;
		long sum = 0;
		long max = 0;
		long latestFrameId = -1;
		long latest = 0;

		for (GpuProfilerFrame frame : history)
		{
			if (!frame.isValid())
			{
				continue;
			}

			boolean available = cpu ? frame.hasCpuNanos(phase) : frame.hasGpuNanos(phase);
			if (!available)
			{
				continue;
			}

			long value = cpu ? frame.getCpuNanos(phase) : frame.getGpuNanos(phase);
			values[count++] = value;
			sum += value;
			max = Math.max(max, value);
			if (frame.getFrameId() > latestFrameId)
			{
				latestFrameId = frame.getFrameId();
				latest = value;
			}
		}

		if (count == 0)
		{
			return new GpuProfilerSnapshot.PhaseStats(phase, 0, 0, 0, 0, 0);
		}

		Arrays.sort(values, 0, count);
		long p95 = values[Math.max(0, (int) Math.ceil(count * 0.95d) - 1)];
		return new GpuProfilerSnapshot.PhaseStats(phase, count, latest, (double) sum / count, p95, max);
	}

	private static GpuProfilerSnapshot.CounterStats counterStats(
		GpuProfilerCounter counter,
		GpuProfilerFrame[] history,
		int sampleCount,
		GpuProfilerFrame latestFrame)
	{
		if (sampleCount == 0)
		{
			return new GpuProfilerSnapshot.CounterStats(counter, 0, 0, 0, 0, 0);
		}

		long total = 0;
		long max = 0;
		for (GpuProfilerFrame frame : history)
		{
			if (!frame.isValid())
			{
				continue;
			}

			long value = frame.getCounter(counter);
			total += value;
			max = Math.max(max, value);
		}

		long latest = latestFrame != null ? latestFrame.getCounter(counter) : 0;
		return new GpuProfilerSnapshot.CounterStats(counter, sampleCount, latest, (double) total / sampleCount, max, total);
	}
}
