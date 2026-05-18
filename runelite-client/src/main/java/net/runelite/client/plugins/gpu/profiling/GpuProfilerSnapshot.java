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

public final class GpuProfilerSnapshot
{
	private final boolean enabled;
	private final String renderer;
	private final String glVersion;
	private final boolean timerQueriesSupported;
	private final boolean debugMarkersSupported;
	private final boolean debugMarkersEnabled;
	private final int sampleCount;
	private final long latestFrameId;
	private final int maxQueryLatencyFrames;
	private final long unavailableQueryCount;
	private final long droppedQueryCount;
	private final PhaseStats[] cpuStats;
	private final PhaseStats[] gpuStats;
	private final CounterStats[] counterStats;

	GpuProfilerSnapshot(
		boolean enabled,
		String renderer,
		String glVersion,
		boolean timerQueriesSupported,
		boolean debugMarkersSupported,
		boolean debugMarkersEnabled,
		int sampleCount,
		long latestFrameId,
		int maxQueryLatencyFrames,
		long unavailableQueryCount,
		long droppedQueryCount,
		PhaseStats[] cpuStats,
		PhaseStats[] gpuStats,
		CounterStats[] counterStats)
	{
		this.enabled = enabled;
		this.renderer = renderer;
		this.glVersion = glVersion;
		this.timerQueriesSupported = timerQueriesSupported;
		this.debugMarkersSupported = debugMarkersSupported;
		this.debugMarkersEnabled = debugMarkersEnabled;
		this.sampleCount = sampleCount;
		this.latestFrameId = latestFrameId;
		this.maxQueryLatencyFrames = maxQueryLatencyFrames;
		this.unavailableQueryCount = unavailableQueryCount;
		this.droppedQueryCount = droppedQueryCount;
		this.cpuStats = cpuStats;
		this.gpuStats = gpuStats;
		this.counterStats = counterStats;
	}

	public boolean isEnabled()
	{
		return enabled;
	}

	public String getRenderer()
	{
		return renderer;
	}

	public String getGlVersion()
	{
		return glVersion;
	}

	public boolean isTimerQueriesSupported()
	{
		return timerQueriesSupported;
	}

	public boolean isDebugMarkersSupported()
	{
		return debugMarkersSupported;
	}

	public boolean isDebugMarkersEnabled()
	{
		return debugMarkersEnabled;
	}

	public int getSampleCount()
	{
		return sampleCount;
	}

	public long getLatestFrameId()
	{
		return latestFrameId;
	}

	public int getMaxQueryLatencyFrames()
	{
		return maxQueryLatencyFrames;
	}

	public long getUnavailableQueryCount()
	{
		return unavailableQueryCount;
	}

	public long getDroppedQueryCount()
	{
		return droppedQueryCount;
	}

	public PhaseStats getCpuStats(GpuProfilerPhase phase)
	{
		return cpuStats[phase.ordinal()];
	}

	public PhaseStats getGpuStats(GpuProfilerPhase phase)
	{
		return gpuStats[phase.ordinal()];
	}

	public CounterStats getCounterStats(GpuProfilerCounter counter)
	{
		return counterStats[counter.ordinal()];
	}

	public static final class PhaseStats
	{
		private final GpuProfilerPhase phase;
		private final int sampleCount;
		private final long latestNanos;
		private final double averageNanos;
		private final long p95Nanos;
		private final long maxNanos;

		PhaseStats(GpuProfilerPhase phase, int sampleCount, long latestNanos, double averageNanos, long p95Nanos, long maxNanos)
		{
			this.phase = phase;
			this.sampleCount = sampleCount;
			this.latestNanos = latestNanos;
			this.averageNanos = averageNanos;
			this.p95Nanos = p95Nanos;
			this.maxNanos = maxNanos;
		}

		public GpuProfilerPhase getPhase()
		{
			return phase;
		}

		public boolean isAvailable()
		{
			return sampleCount > 0;
		}

		public int getSampleCount()
		{
			return sampleCount;
		}

		public long getLatestNanos()
		{
			return latestNanos;
		}

		public double getAverageNanos()
		{
			return averageNanos;
		}

		public long getP95Nanos()
		{
			return p95Nanos;
		}

		public long getMaxNanos()
		{
			return maxNanos;
		}
	}

	public static final class CounterStats
	{
		private final GpuProfilerCounter counter;
		private final int sampleCount;
		private final long latest;
		private final double average;
		private final long max;
		private final long total;

		CounterStats(GpuProfilerCounter counter, int sampleCount, long latest, double average, long max, long total)
		{
			this.counter = counter;
			this.sampleCount = sampleCount;
			this.latest = latest;
			this.average = average;
			this.max = max;
			this.total = total;
		}

		public GpuProfilerCounter getCounter()
		{
			return counter;
		}

		public int getSampleCount()
		{
			return sampleCount;
		}

		public long getLatest()
		{
			return latest;
		}

		public double getAverage()
		{
			return average;
		}

		public long getMax()
		{
			return max;
		}

		public long getTotal()
		{
			return total;
		}
	}
}
