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
import lombok.extern.slf4j.Slf4j;
import org.lwjgl.opengl.GLCapabilities;
import static org.lwjgl.opengl.GL15C.GL_QUERY_RESULT;
import static org.lwjgl.opengl.GL15C.GL_QUERY_RESULT_AVAILABLE;
import static org.lwjgl.opengl.GL15C.glBeginQuery;
import static org.lwjgl.opengl.GL15C.glDeleteQueries;
import static org.lwjgl.opengl.GL15C.glEndQuery;
import static org.lwjgl.opengl.GL15C.glGenQueries;
import static org.lwjgl.opengl.GL15C.glGetQueryObjecti;
import static org.lwjgl.opengl.GL33C.GL_TIME_ELAPSED;
import static org.lwjgl.opengl.GL33C.glGetQueryObjectui64;
import static org.lwjgl.opengl.GL43C.GL_DEBUG_SOURCE_APPLICATION;
import static org.lwjgl.opengl.GL43C.glObjectLabel;
import static org.lwjgl.opengl.GL43C.glPopDebugGroup;
import static org.lwjgl.opengl.GL43C.glPushDebugGroup;

@Slf4j
public final class GpuProfiler
{
	private static final int QUERY_RING_SIZE = 8;
	private static final int HISTORY_SIZE = 300;
	private static final int PHASE_COUNT = GpuProfilerPhase.VALUES.length;
	private static final int COUNTER_COUNT = GpuProfilerCounter.VALUES.length;

	private final QueryFrame[] queryFrames = new QueryFrame[QUERY_RING_SIZE];
	private final GpuProfilerFrame[] history = new GpuProfilerFrame[HISTORY_SIZE];
	private final long[] pendingCpuNanos = new long[PHASE_COUNT];
	private final long[] pendingCpuStartNanos = new long[PHASE_COUNT];
	private final long[] pendingCounters = new long[COUNTER_COUNT];
	private final GpuProfilerGl gl;

	private volatile boolean enabled;
	private boolean timerQueriesSupported;
	private boolean debugMarkersSupported;
	private boolean debugMarkersEnabled;
	private boolean timerFailureLogged;
	private boolean debugFailureLogged;
	private String renderer = "";
	private String glVersion = "";
	private long runId = System.currentTimeMillis();
	private long nextFrameId;
	private boolean frameActive;
	private QueryFrame currentQueryFrame;
	private GpuProfilerFrame currentFrame;
	private GpuProfilerPhase activeGpuPhase;
	private GpuProfilerPhase activeDebugPhase;

	public GpuProfiler()
	{
		this(new LwjglGpuProfilerGl());
	}

	GpuProfiler(GpuProfilerGl gl)
	{
		for (int i = 0; i < queryFrames.length; ++i)
		{
			queryFrames[i] = new QueryFrame();
		}
		for (int i = 0; i < history.length; ++i)
		{
			history[i] = new GpuProfilerFrame();
		}
		this.gl = gl;
	}

	public synchronized void start(GLCapabilities capabilities, String renderer, String glVersion, boolean debugMarkersEnabled)
	{
		if (enabled)
		{
			this.debugMarkersEnabled = debugMarkersEnabled;
			return;
		}

		this.renderer = renderer != null ? renderer : "";
		this.glVersion = glVersion != null ? glVersion : "";
		this.debugMarkersEnabled = debugMarkersEnabled;
		boolean timerQueriesSupported = capabilities != null
			&& capabilities.OpenGL33
			&& capabilities.glBeginQuery != 0
			&& capabilities.glGetQueryObjectiv != 0
			&& capabilities.glGetQueryObjectui64v != 0;
		boolean debugMarkersSupported = capabilities != null
			&& capabilities.GL_KHR_debug
			&& capabilities.glPushDebugGroup != 0
			&& capabilities.glObjectLabel != 0;
		start(renderer, glVersion, timerQueriesSupported, debugMarkersSupported, debugMarkersEnabled);
	}

	synchronized void start(
		String renderer,
		String glVersion,
		boolean timerQueriesSupported,
		boolean debugMarkersSupported,
		boolean debugMarkersEnabled)
	{
		if (enabled)
		{
			this.debugMarkersEnabled = debugMarkersEnabled;
			return;
		}

		this.renderer = renderer != null ? renderer : "";
		this.glVersion = glVersion != null ? glVersion : "";
		this.debugMarkersEnabled = debugMarkersEnabled;
		this.timerQueriesSupported = timerQueriesSupported;
		this.debugMarkersSupported = debugMarkersSupported;
		this.timerFailureLogged = false;
		this.debugFailureLogged = false;
		this.runId = System.currentTimeMillis();
		this.nextFrameId = 0;
		clearSamples();

		if (timerQueriesSupported)
		{
			try
			{
				for (QueryFrame queryFrame : queryFrames)
				{
					queryFrame.allocateQueries();
				}
			}
			catch (RuntimeException ex)
			{
				timerQueriesSupported = false;
				this.timerQueriesSupported = false;
				deleteQueries();
				log.warn("GPU profiler timer queries are unavailable; CPU timings will still be collected", ex);
			}
		}

		enabled = true;
		log.info("GPU profiler enabled. timerQueriesSupported={} debugMarkersSupported={}", timerQueriesSupported, debugMarkersSupported);
	}

	public synchronized void stop()
	{
		if (!enabled && !timerQueriesSupported)
		{
			return;
		}

		if (activeGpuPhase != null)
		{
			try
			{
				gl.endTimerQuery();
			}
			catch (RuntimeException ex)
			{
				log.debug("Unable to end active GPU profiler query during shutdown", ex);
			}
			activeGpuPhase = null;
		}
		if (activeDebugPhase != null)
		{
			try
			{
				gl.popDebugGroup();
			}
			catch (RuntimeException ex)
			{
				log.debug("Unable to pop active GPU profiler debug group during shutdown", ex);
			}
			activeDebugPhase = null;
		}

		deleteQueries();
		frameActive = false;
		currentQueryFrame = null;
		currentFrame = null;
		timerQueriesSupported = false;
		debugMarkersSupported = false;
		enabled = false;
	}

	public synchronized void reset()
	{
		clearSamples();
		runId = System.currentTimeMillis();
	}

	private void clearSamples()
	{
		for (GpuProfilerFrame frame : history)
		{
			frame.clear();
		}
		Arrays.fill(pendingCpuNanos, 0);
		Arrays.fill(pendingCpuStartNanos, 0);
		Arrays.fill(pendingCounters, 0);
	}

	private void deleteQueries()
	{
		for (QueryFrame queryFrame : queryFrames)
		{
			try
			{
				queryFrame.deleteQueries();
			}
			catch (RuntimeException ex)
			{
				log.debug("Unable to delete GPU profiler timer queries", ex);
			}
		}
	}

	public boolean isEnabled()
	{
		return enabled;
	}

	public synchronized boolean isTimerQueriesSupported()
	{
		return timerQueriesSupported;
	}

	public synchronized boolean isDebugMarkersSupported()
	{
		return debugMarkersSupported;
	}

	public synchronized boolean isDebugMarkersEnabled()
	{
		return debugMarkersEnabled && debugMarkersSupported;
	}

	public synchronized void beginFrame(
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
		int colorBlindIntensity)
	{
		if (!enabled || frameActive)
		{
			return;
		}

		int queryFrameIndex = (int) (nextFrameId % queryFrames.length);
		QueryFrame queryFrame = queryFrames[queryFrameIndex];
		pollQueryFrame(queryFrame);
		queryFrame.resetForFrame();

		currentQueryFrame = queryFrame;
		currentFrame = queryFrame.frame;
		long frameId = nextFrameId++;
		currentFrame.setMetadata(
			runId,
			frameId,
			System.currentTimeMillis(),
			canvasWidth,
			canvasHeight,
			stretchedWidth,
			stretchedHeight,
			renderTargetWidth,
			renderTargetHeight,
			stretchedMode,
			drawDistance,
			expandedMapLoadingChunks,
			antiAliasingMode,
			anisotropicFilteringLevel,
			uiScalingMode,
			unlockFps,
			syncMode,
			fpsTarget,
			fogDepth,
			colorBlindIntensity,
			timerQueriesSupported,
			debugMarkersSupported,
			debugMarkersEnabled);
		for (GpuProfilerPhase phase : GpuProfilerPhase.VALUES)
		{
			int idx = phase.ordinal();
			if (pendingCpuNanos[idx] != 0)
			{
				currentFrame.addCpuNanos(phase, pendingCpuNanos[idx]);
				pendingCpuNanos[idx] = 0;
			}
		}
		for (GpuProfilerCounter counter : GpuProfilerCounter.VALUES)
		{
			int idx = counter.ordinal();
			if (pendingCounters[idx] != 0)
			{
				currentFrame.incrementCounter(counter, pendingCounters[idx]);
				pendingCounters[idx] = 0;
			}
		}

		frameActive = true;
		currentFrame.beginCpu(GpuProfilerPhase.FRAME, System.nanoTime());
	}

	public synchronized void endFrame()
	{
		if (!enabled || !frameActive)
		{
			return;
		}

		if (activeGpuPhase != null || activeDebugPhase != null)
		{
			endGpuPhase(activeGpuPhase != null ? activeGpuPhase : activeDebugPhase);
		}

		currentFrame.endCpu(GpuProfilerPhase.FRAME, System.nanoTime());
		copyCurrentFrameToHistory();
		currentQueryFrame.submitted = timerQueriesSupported;
		currentQueryFrame.frameId = currentFrame.getFrameId();
		frameActive = false;
		currentQueryFrame = null;
		currentFrame = null;
	}

	public synchronized void beginPhase(GpuProfilerPhase phase)
	{
		if (!enabled)
		{
			return;
		}

		beginCpuPhase(phase);
		beginGpuPhase(phase);
	}

	public synchronized void endPhase(GpuProfilerPhase phase)
	{
		if (!enabled)
		{
			return;
		}

		endGpuPhase(phase);
		endCpuPhase(phase);
	}

	public synchronized void beginCpuPhase(GpuProfilerPhase phase)
	{
		if (!enabled)
		{
			return;
		}

		long now = System.nanoTime();
		if (frameActive)
		{
			currentFrame.beginCpu(phase, now);
		}
		else
		{
			pendingCpuStartNanos[phase.ordinal()] = now;
		}
	}

	public synchronized void endCpuPhase(GpuProfilerPhase phase)
	{
		if (!enabled)
		{
			return;
		}

		long now = System.nanoTime();
		if (frameActive)
		{
			currentFrame.endCpu(phase, now);
			return;
		}

		int idx = phase.ordinal();
		long start = pendingCpuStartNanos[idx];
		if (start != 0)
		{
			pendingCpuNanos[idx] += now - start;
			pendingCpuStartNanos[idx] = 0;
		}
	}

	public synchronized void addCpuNanos(GpuProfilerPhase phase, long nanos)
	{
		if (!enabled || nanos <= 0)
		{
			return;
		}

		if (frameActive)
		{
			currentFrame.addCpuNanos(phase, nanos);
		}
		else
		{
			pendingCpuNanos[phase.ordinal()] += nanos;
		}
	}

	public synchronized void beginGpuPhase(GpuProfilerPhase phase)
	{
		if (!enabled || !frameActive || !phase.isGpuTimed())
		{
			return;
		}

		if (activeGpuPhase != null || activeDebugPhase != null)
		{
			return;
		}

		try
		{
			if (debugMarkersEnabled && debugMarkersSupported)
			{
				gl.pushDebugGroup(phase.ordinal(), "RuneLite GPU: " + phase.getDisplayName());
				activeDebugPhase = phase;
			}

			if (timerQueriesSupported && !currentQueryFrame.issued[phase.ordinal()])
			{
				gl.beginTimerQuery(currentQueryFrame.queries[phase.ordinal()]);
				currentQueryFrame.issued[phase.ordinal()] = true;
				activeGpuPhase = phase;
			}
		}
		catch (RuntimeException ex)
		{
			handleGlProfilerFailure(ex);
		}
	}

	public synchronized void endGpuPhase(GpuProfilerPhase phase)
	{
		if (!enabled)
		{
			return;
		}

		try
		{
			if (activeGpuPhase == phase)
			{
				gl.endTimerQuery();
				activeGpuPhase = null;
			}
			if (activeDebugPhase == phase)
			{
				gl.popDebugGroup();
				activeDebugPhase = null;
			}
		}
		catch (RuntimeException ex)
		{
			handleGlProfilerFailure(ex);
		}
	}

	public synchronized void incrementCounter(GpuProfilerCounter counter)
	{
		incrementCounter(counter, 1);
	}

	public synchronized void incrementCounter(GpuProfilerCounter counter, long amount)
	{
		if (!enabled || amount == 0)
		{
			return;
		}

		if (frameActive)
		{
			currentFrame.incrementCounter(counter, amount);
		}
		else
		{
			pendingCounters[counter.ordinal()] += amount;
		}
	}

	public synchronized void labelObject(int identifier, int object, String label)
	{
		if (!enabled || !debugMarkersEnabled || !debugMarkersSupported || object <= 0)
		{
			return;
		}

		try
		{
			gl.objectLabel(identifier, object, "RuneLite GPU: " + label);
		}
		catch (RuntimeException ex)
		{
			if (!debugFailureLogged)
			{
				debugFailureLogged = true;
				log.warn("GPU profiler debug labels are unavailable", ex);
			}
			debugMarkersSupported = false;
		}
	}

	public synchronized GpuProfilerSnapshot snapshot()
	{
		return GpuProfilerStats.snapshot(
			enabled,
			renderer,
			glVersion,
			timerQueriesSupported,
			debugMarkersSupported,
			debugMarkersEnabled,
			history);
	}

	public synchronized String exportCsv()
	{
		return GpuProfilerExport.toCsv(renderer, glVersion, history);
	}

	private void handleGlProfilerFailure(RuntimeException ex)
	{
		if (!timerFailureLogged)
		{
			timerFailureLogged = true;
			log.warn("GPU profiler GL instrumentation failed; continuing with CPU-only profiler data", ex);
		}
		if (activeDebugPhase != null)
		{
			try
			{
				gl.popDebugGroup();
			}
			catch (RuntimeException ignored)
			{
				// The original exception is the useful one.
			}
		}
		timerQueriesSupported = false;
		debugMarkersSupported = false;
		activeGpuPhase = null;
		activeDebugPhase = null;
	}

	private void copyCurrentFrameToHistory()
	{
		int historyIndex = (int) (currentFrame.getFrameId() % history.length);
		history[historyIndex].copyFrom(currentFrame);
	}

	private void pollQueryFrame(QueryFrame queryFrame)
	{
		if (!timerQueriesSupported || !queryFrame.submitted)
		{
			return;
		}

		GpuProfilerFrame historyFrame = historyFrame(queryFrame.frameId);
		int unavailable = 0;
		int latencyFrames = (int) Math.max(0, nextFrameId - queryFrame.frameId);
		for (GpuProfilerPhase phase : GpuProfilerPhase.VALUES)
		{
			if (!phase.isGpuTimed() || !queryFrame.issued[phase.ordinal()])
			{
				continue;
			}

			int query = queryFrame.queries[phase.ordinal()];
			boolean available;
			try
			{
				available = gl.isQueryResultAvailable(query);
			}
			catch (RuntimeException ex)
			{
				handleGlProfilerFailure(ex);
				return;
			}

			if (!available)
			{
				++unavailable;
				try
				{
					gl.deleteQuery(query);
					queryFrame.queries[phase.ordinal()] = gl.genQuery();
				}
				catch (RuntimeException ex)
				{
					handleGlProfilerFailure(ex);
					return;
				}
				continue;
			}

			try
			{
				long elapsed = gl.getQueryResult(query);
				if (historyFrame != null)
				{
					historyFrame.setGpuNanos(phase, elapsed);
				}
			}
			catch (RuntimeException ex)
			{
				handleGlProfilerFailure(ex);
				return;
			}
		}

		if (historyFrame != null)
		{
			historyFrame.setQueryResultMetadata(latencyFrames, unavailable, unavailable);
		}

		queryFrame.submitted = false;
		Arrays.fill(queryFrame.issued, false);
	}

	private GpuProfilerFrame historyFrame(long frameId)
	{
		int historyIndex = (int) (frameId % history.length);
		GpuProfilerFrame frame = history[historyIndex];
		return frame.isValid() && frame.getFrameId() == frameId ? frame : null;
	}

	private final class QueryFrame
	{
		private final GpuProfilerFrame frame = new GpuProfilerFrame();
		private final int[] queries = new int[PHASE_COUNT];
		private final boolean[] issued = new boolean[PHASE_COUNT];
		private boolean submitted;
		private long frameId;

		private void allocateQueries()
		{
			for (GpuProfilerPhase phase : GpuProfilerPhase.VALUES)
			{
				if (phase.isGpuTimed() && queries[phase.ordinal()] == 0)
				{
					queries[phase.ordinal()] = gl.genQuery();
				}
			}
		}

		private void deleteQueries()
		{
			RuntimeException failure = null;
			for (int i = 0; i < queries.length; ++i)
			{
				if (queries[i] != 0)
				{
					try
					{
						gl.deleteQuery(queries[i]);
					}
					catch (RuntimeException ex)
					{
						if (failure == null)
						{
							failure = ex;
						}
					}
					queries[i] = 0;
				}
			}
			Arrays.fill(issued, false);
			submitted = false;
			frame.clear();
			if (failure != null)
			{
				throw failure;
			}
		}

		private void resetForFrame()
		{
			frame.clear();
			Arrays.fill(issued, false);
			submitted = false;
			frameId = 0;
		}
	}

	private static final class LwjglGpuProfilerGl implements GpuProfilerGl
	{
		@Override
		public int genQuery()
		{
			return glGenQueries();
		}

		@Override
		public void deleteQuery(int query)
		{
			glDeleteQueries(query);
		}

		@Override
		public void beginTimerQuery(int query)
		{
			glBeginQuery(GL_TIME_ELAPSED, query);
		}

		@Override
		public void endTimerQuery()
		{
			glEndQuery(GL_TIME_ELAPSED);
		}

		@Override
		public boolean isQueryResultAvailable(int query)
		{
			return glGetQueryObjecti(query, GL_QUERY_RESULT_AVAILABLE) != 0;
		}

		@Override
		public long getQueryResult(int query)
		{
			return glGetQueryObjectui64(query, GL_QUERY_RESULT);
		}

		@Override
		public void pushDebugGroup(int id, String label)
		{
			glPushDebugGroup(GL_DEBUG_SOURCE_APPLICATION, id, label);
		}

		@Override
		public void popDebugGroup()
		{
			glPopDebugGroup();
		}

		@Override
		public void objectLabel(int identifier, int object, String label)
		{
			glObjectLabel(identifier, object, label);
		}
	}
}
