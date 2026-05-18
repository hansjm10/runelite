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
import java.util.Comparator;
import java.util.Locale;

public final class GpuProfilerExport
{
	private static final Comparator<GpuProfilerFrame> FRAME_ORDER = (a, b) ->
	{
		int run = Long.compare(a.getRunId(), b.getRunId());
		return run != 0 ? run : Long.compare(a.getFrameId(), b.getFrameId());
	};

	private GpuProfilerExport()
	{
	}

	public static String toCsv(String renderer, String glVersion, GpuProfilerFrame[] history)
	{
		GpuProfilerFrame[] frames = new GpuProfilerFrame[history.length];
		int count = 0;
		for (GpuProfilerFrame frame : history)
		{
			if (frame.isValid())
			{
				frames[count++] = frame;
			}
		}
		Arrays.sort(frames, 0, count, FRAME_ORDER);

		StringBuilder out = new StringBuilder(Math.max(1024, count * 1024));
		appendHeader(out);
		for (int i = 0; i < count; ++i)
		{
			appendFrame(out, renderer, glVersion, frames[i]);
		}
		return out.toString();
	}

	private static void appendHeader(StringBuilder out)
	{
		appendColumn(out, "run_id");
		appendColumn(out, "frame_id");
		appendColumn(out, "capture_time_ms");
		appendColumn(out, "renderer");
		appendColumn(out, "gl_version");
		appendColumn(out, "timer_queries_supported");
		appendColumn(out, "debug_markers_supported");
		appendColumn(out, "debug_markers_enabled");
		appendColumn(out, "canvas_width");
		appendColumn(out, "canvas_height");
		appendColumn(out, "stretched_width");
		appendColumn(out, "stretched_height");
		appendColumn(out, "render_target_width");
		appendColumn(out, "render_target_height");
		appendColumn(out, "stretched_mode");
		appendColumn(out, "draw_distance");
		appendColumn(out, "expanded_map_loading_chunks");
		appendColumn(out, "anti_aliasing_mode");
		appendColumn(out, "anisotropic_filtering_level");
		appendColumn(out, "ui_scaling_mode");
		appendColumn(out, "unlock_fps");
		appendColumn(out, "sync_mode");
		appendColumn(out, "fps_target");
		appendColumn(out, "fog_depth");
		appendColumn(out, "colorblind_intensity");
		appendColumn(out, "query_latency_frames");
		appendColumn(out, "unavailable_gpu_queries");
		appendColumn(out, "dropped_gpu_queries");
		for (GpuProfilerCounter counter : GpuProfilerCounter.VALUES)
		{
			appendColumn(out, "counter_" + counter.getCsvName());
		}
		for (GpuProfilerPhase phase : GpuProfilerPhase.VALUES)
		{
			appendColumn(out, "cpu_" + phase.getCsvName() + "_ms");
			appendColumn(out, "gpu_" + phase.getCsvName() + "_ms");
		}
		out.setLength(out.length() - 1);
		out.append('\n');
	}

	private static void appendFrame(StringBuilder out, String renderer, String glVersion, GpuProfilerFrame frame)
	{
		appendColumn(out, frame.getRunId());
		appendColumn(out, frame.getFrameId());
		appendColumn(out, frame.getCaptureTimeMillis());
		appendColumn(out, renderer);
		appendColumn(out, glVersion);
		appendColumn(out, frame.isTimerQueriesSupported());
		appendColumn(out, frame.isDebugMarkersSupported());
		appendColumn(out, frame.isDebugMarkersEnabled());
		appendColumn(out, frame.getCanvasWidth());
		appendColumn(out, frame.getCanvasHeight());
		appendColumn(out, frame.getStretchedWidth());
		appendColumn(out, frame.getStretchedHeight());
		appendColumn(out, frame.getRenderTargetWidth());
		appendColumn(out, frame.getRenderTargetHeight());
		appendColumn(out, frame.isStretchedMode());
		appendColumn(out, frame.getDrawDistance());
		appendColumn(out, frame.getExpandedMapLoadingChunks());
		appendColumn(out, frame.getAntiAliasingMode());
		appendColumn(out, frame.getAnisotropicFilteringLevel());
		appendColumn(out, frame.getUiScalingMode());
		appendColumn(out, frame.isUnlockFps());
		appendColumn(out, frame.getSyncMode());
		appendColumn(out, frame.getFpsTarget());
		appendColumn(out, frame.getFogDepth());
		appendColumn(out, frame.getColorBlindIntensity());
		appendColumn(out, frame.getQueryLatencyFrames());
		appendColumn(out, frame.getUnavailableQueryCount());
		appendColumn(out, frame.getDroppedQueryCount());
		for (GpuProfilerCounter counter : GpuProfilerCounter.VALUES)
		{
			appendColumn(out, frame.getCounter(counter));
		}
		for (GpuProfilerPhase phase : GpuProfilerPhase.VALUES)
		{
			appendDurationColumn(out, frame.hasCpuNanos(phase), frame.getCpuNanos(phase));
			appendDurationColumn(out, frame.hasGpuNanos(phase), frame.getGpuNanos(phase));
		}
		out.setLength(out.length() - 1);
		out.append('\n');
	}

	private static void appendDurationColumn(StringBuilder out, boolean available, long nanos)
	{
		if (available)
		{
			appendColumn(out, nanosToMillis(nanos));
		}
		else
		{
			out.append(',');
		}
	}

	static String nanosToMillis(long nanos)
	{
		return String.format(Locale.ROOT, "%.3f", nanos / 1_000_000d);
	}

	private static void appendColumn(StringBuilder out, long value)
	{
		out.append(value).append(',');
	}

	private static void appendColumn(StringBuilder out, int value)
	{
		out.append(value).append(',');
	}

	private static void appendColumn(StringBuilder out, boolean value)
	{
		out.append(value).append(',');
	}

	private static void appendColumn(StringBuilder out, String value)
	{
		if (value.indexOf(',') == -1 && value.indexOf('"') == -1 && value.indexOf('\n') == -1 && value.indexOf('\r') == -1)
		{
			out.append(value).append(',');
			return;
		}

		out.append('"');
		for (int i = 0; i < value.length(); ++i)
		{
			char c = value.charAt(i);
			if (c == '"')
			{
				out.append('"');
			}
			out.append(c);
		}
		out.append('"').append(',');
	}
}
