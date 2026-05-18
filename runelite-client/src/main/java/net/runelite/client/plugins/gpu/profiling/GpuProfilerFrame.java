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

import java.util.Arrays;

public final class GpuProfilerFrame
{
	private static final int PHASE_COUNT = GpuProfilerPhase.VALUES.length;
	private static final int COUNTER_COUNT = GpuProfilerCounter.VALUES.length;

	private final long[] cpuStartNanos = new long[PHASE_COUNT];
	private final long[] cpuNanos = new long[PHASE_COUNT];
	private final boolean[] cpuAvailable = new boolean[PHASE_COUNT];
	private final long[] gpuNanos = new long[PHASE_COUNT];
	private final boolean[] gpuAvailable = new boolean[PHASE_COUNT];
	private final long[] counters = new long[COUNTER_COUNT];

	private boolean valid;
	private long runId;
	private long frameId;
	private long captureTimeMillis;
	private int canvasWidth;
	private int canvasHeight;
	private int stretchedWidth;
	private int stretchedHeight;
	private int renderTargetWidth;
	private int renderTargetHeight;
	private boolean stretchedMode;
	private int drawDistance;
	private int expandedMapLoadingChunks;
	private String antiAliasingMode = "";
	private int anisotropicFilteringLevel;
	private String uiScalingMode = "";
	private boolean unlockFps;
	private String syncMode = "";
	private int fpsTarget;
	private int fogDepth;
	private int colorBlindIntensity;
	private boolean timerQueriesSupported;
	private boolean debugMarkersSupported;
	private boolean debugMarkersEnabled;
	private int queryLatencyFrames = -1;
	private int unavailableQueryCount;
	private int droppedQueryCount;

	public void clear()
	{
		valid = false;
		runId = 0;
		frameId = 0;
		captureTimeMillis = 0;
		canvasWidth = 0;
		canvasHeight = 0;
		stretchedWidth = 0;
		stretchedHeight = 0;
		renderTargetWidth = 0;
		renderTargetHeight = 0;
		stretchedMode = false;
		drawDistance = 0;
		expandedMapLoadingChunks = 0;
		antiAliasingMode = "";
		anisotropicFilteringLevel = 0;
		uiScalingMode = "";
		unlockFps = false;
		syncMode = "";
		fpsTarget = 0;
		fogDepth = 0;
		colorBlindIntensity = 0;
		timerQueriesSupported = false;
		debugMarkersSupported = false;
		debugMarkersEnabled = false;
		queryLatencyFrames = -1;
		unavailableQueryCount = 0;
		droppedQueryCount = 0;
		Arrays.fill(cpuStartNanos, 0);
		Arrays.fill(cpuNanos, 0);
		Arrays.fill(cpuAvailable, false);
		Arrays.fill(gpuNanos, 0);
		Arrays.fill(gpuAvailable, false);
		Arrays.fill(counters, 0);
	}

	public void copyFrom(GpuProfilerFrame frame)
	{
		valid = frame.valid;
		runId = frame.runId;
		frameId = frame.frameId;
		captureTimeMillis = frame.captureTimeMillis;
		canvasWidth = frame.canvasWidth;
		canvasHeight = frame.canvasHeight;
		stretchedWidth = frame.stretchedWidth;
		stretchedHeight = frame.stretchedHeight;
		renderTargetWidth = frame.renderTargetWidth;
		renderTargetHeight = frame.renderTargetHeight;
		stretchedMode = frame.stretchedMode;
		drawDistance = frame.drawDistance;
		expandedMapLoadingChunks = frame.expandedMapLoadingChunks;
		antiAliasingMode = frame.antiAliasingMode;
		anisotropicFilteringLevel = frame.anisotropicFilteringLevel;
		uiScalingMode = frame.uiScalingMode;
		unlockFps = frame.unlockFps;
		syncMode = frame.syncMode;
		fpsTarget = frame.fpsTarget;
		fogDepth = frame.fogDepth;
		colorBlindIntensity = frame.colorBlindIntensity;
		timerQueriesSupported = frame.timerQueriesSupported;
		debugMarkersSupported = frame.debugMarkersSupported;
		debugMarkersEnabled = frame.debugMarkersEnabled;
		queryLatencyFrames = frame.queryLatencyFrames;
		unavailableQueryCount = frame.unavailableQueryCount;
		droppedQueryCount = frame.droppedQueryCount;
		System.arraycopy(frame.cpuStartNanos, 0, cpuStartNanos, 0, cpuStartNanos.length);
		System.arraycopy(frame.cpuNanos, 0, cpuNanos, 0, cpuNanos.length);
		System.arraycopy(frame.cpuAvailable, 0, cpuAvailable, 0, cpuAvailable.length);
		System.arraycopy(frame.gpuNanos, 0, gpuNanos, 0, gpuNanos.length);
		System.arraycopy(frame.gpuAvailable, 0, gpuAvailable, 0, gpuAvailable.length);
		System.arraycopy(frame.counters, 0, counters, 0, counters.length);
	}

	void setMetadata(
		long runId,
		long frameId,
		long captureTimeMillis,
		int canvasWidth,
		int canvasHeight,
		int stretchedWidth,
		int stretchedHeight,
		int renderTargetWidth,
		int renderTargetHeight,
		boolean stretchedMode,
		int drawDistance,
		int expandedMapLoadingChunks,
		String antiAliasingMode,
		int anisotropicFilteringLevel,
		String uiScalingMode,
		boolean unlockFps,
		String syncMode,
		int fpsTarget,
		int fogDepth,
		int colorBlindIntensity,
		boolean timerQueriesSupported,
		boolean debugMarkersSupported,
		boolean debugMarkersEnabled)
	{
		this.valid = true;
		this.runId = runId;
		this.frameId = frameId;
		this.captureTimeMillis = captureTimeMillis;
		this.canvasWidth = canvasWidth;
		this.canvasHeight = canvasHeight;
		this.stretchedWidth = stretchedWidth;
		this.stretchedHeight = stretchedHeight;
		this.renderTargetWidth = renderTargetWidth;
		this.renderTargetHeight = renderTargetHeight;
		this.stretchedMode = stretchedMode;
		this.drawDistance = drawDistance;
		this.expandedMapLoadingChunks = expandedMapLoadingChunks;
		this.antiAliasingMode = antiAliasingMode;
		this.anisotropicFilteringLevel = anisotropicFilteringLevel;
		this.uiScalingMode = uiScalingMode;
		this.unlockFps = unlockFps;
		this.syncMode = syncMode;
		this.fpsTarget = fpsTarget;
		this.fogDepth = fogDepth;
		this.colorBlindIntensity = colorBlindIntensity;
		this.timerQueriesSupported = timerQueriesSupported;
		this.debugMarkersSupported = debugMarkersSupported;
		this.debugMarkersEnabled = debugMarkersEnabled;
	}

	void beginCpu(GpuProfilerPhase phase, long now)
	{
		cpuStartNanos[phase.ordinal()] = now;
	}

	void endCpu(GpuProfilerPhase phase, long now)
	{
		int idx = phase.ordinal();
		long start = cpuStartNanos[idx];
		if (start == 0)
		{
			return;
		}

		cpuNanos[idx] += now - start;
		cpuAvailable[idx] = true;
		cpuStartNanos[idx] = 0;
	}

	void addCpuNanos(GpuProfilerPhase phase, long nanos)
	{
		int idx = phase.ordinal();
		cpuNanos[idx] += nanos;
		cpuAvailable[idx] = true;
	}

	void setGpuNanos(GpuProfilerPhase phase, long nanos)
	{
		int idx = phase.ordinal();
		gpuNanos[idx] = nanos;
		gpuAvailable[idx] = true;
	}

	void incrementCounter(GpuProfilerCounter counter, long amount)
	{
		counters[counter.ordinal()] += amount;
	}

	void setQueryResultMetadata(int queryLatencyFrames, int unavailableQueryCount, int droppedQueryCount)
	{
		this.queryLatencyFrames = queryLatencyFrames;
		this.unavailableQueryCount = unavailableQueryCount;
		this.droppedQueryCount = droppedQueryCount;
	}

	public boolean isValid()
	{
		return valid;
	}

	public long getRunId()
	{
		return runId;
	}

	public long getFrameId()
	{
		return frameId;
	}

	public long getCaptureTimeMillis()
	{
		return captureTimeMillis;
	}

	public int getCanvasWidth()
	{
		return canvasWidth;
	}

	public int getCanvasHeight()
	{
		return canvasHeight;
	}

	public int getStretchedWidth()
	{
		return stretchedWidth;
	}

	public int getStretchedHeight()
	{
		return stretchedHeight;
	}

	public int getRenderTargetWidth()
	{
		return renderTargetWidth;
	}

	public int getRenderTargetHeight()
	{
		return renderTargetHeight;
	}

	public boolean isStretchedMode()
	{
		return stretchedMode;
	}

	public int getDrawDistance()
	{
		return drawDistance;
	}

	public int getExpandedMapLoadingChunks()
	{
		return expandedMapLoadingChunks;
	}

	public String getAntiAliasingMode()
	{
		return antiAliasingMode;
	}

	public int getAnisotropicFilteringLevel()
	{
		return anisotropicFilteringLevel;
	}

	public String getUiScalingMode()
	{
		return uiScalingMode;
	}

	public boolean isUnlockFps()
	{
		return unlockFps;
	}

	public String getSyncMode()
	{
		return syncMode;
	}

	public int getFpsTarget()
	{
		return fpsTarget;
	}

	public int getFogDepth()
	{
		return fogDepth;
	}

	public int getColorBlindIntensity()
	{
		return colorBlindIntensity;
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

	public int getQueryLatencyFrames()
	{
		return queryLatencyFrames;
	}

	public int getUnavailableQueryCount()
	{
		return unavailableQueryCount;
	}

	public int getDroppedQueryCount()
	{
		return droppedQueryCount;
	}

	public boolean hasCpuNanos(GpuProfilerPhase phase)
	{
		return cpuAvailable[phase.ordinal()];
	}

	public long getCpuNanos(GpuProfilerPhase phase)
	{
		return cpuNanos[phase.ordinal()];
	}

	public boolean hasGpuNanos(GpuProfilerPhase phase)
	{
		return gpuAvailable[phase.ordinal()];
	}

	public long getGpuNanos(GpuProfilerPhase phase)
	{
		return gpuNanos[phase.ordinal()];
	}

	public long getCounter(GpuProfilerCounter counter)
	{
		return counters[counter.ordinal()];
	}
}
