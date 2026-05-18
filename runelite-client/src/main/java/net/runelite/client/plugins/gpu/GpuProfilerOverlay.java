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
package net.runelite.client.plugins.gpu;

import java.awt.Color;
import java.awt.Dimension;
import java.awt.Graphics2D;
import java.util.Locale;
import javax.inject.Inject;
import static net.runelite.api.MenuAction.RUNELITE_OVERLAY;
import static net.runelite.api.MenuAction.RUNELITE_OVERLAY_CONFIG;
import net.runelite.client.plugins.gpu.profiling.GpuProfilerCounter;
import net.runelite.client.plugins.gpu.profiling.GpuProfilerPhase;
import net.runelite.client.plugins.gpu.profiling.GpuProfilerSnapshot;
import static net.runelite.client.ui.overlay.OverlayManager.OPTION_CONFIGURE;
import net.runelite.client.ui.overlay.OverlayPanel;
import net.runelite.client.ui.overlay.OverlayPosition;
import net.runelite.client.ui.overlay.components.LineComponent;
import net.runelite.client.ui.overlay.components.TitleComponent;

class GpuProfilerOverlay extends OverlayPanel
{
	private static final Color SECTION = new Color(255, 200, 0);
	private static final Color UNAVAILABLE = Color.GRAY;

	private final GpuPlugin plugin;
	private final GpuPluginConfig config;

	@Inject
	private GpuProfilerOverlay(GpuPlugin plugin, GpuPluginConfig config)
	{
		super(plugin);
		this.plugin = plugin;
		this.config = config;
		setPosition(OverlayPosition.TOP_LEFT);
		setPriority(PRIORITY_LOW);
		setPreferredSize(new Dimension(420, 0));
		addMenuEntry(RUNELITE_OVERLAY_CONFIG, OPTION_CONFIGURE, "GPU profiler overlay");
		addMenuEntry(RUNELITE_OVERLAY, "Reset", "GPU profiler", e -> plugin.resetGpuProfilerSamples());
		addMenuEntry(RUNELITE_OVERLAY, "Export CSV", "GPU profiler", e -> plugin.exportGpuProfilerSamples());
	}

	@Override
	public Dimension render(Graphics2D graphics)
	{
		if (!config.gpuProfiler() || !config.gpuProfilerOverlay())
		{
			return null;
		}

		GpuProfilerSnapshot snapshot = plugin.getGpuProfilerSnapshot();
		panelComponent.getChildren().add(TitleComponent.builder()
			.text("GPU Profiler")
			.color(SECTION)
			.build());
		panelComponent.getChildren().add(LineComponent.builder()
			.left("Samples")
			.right(Integer.toString(snapshot.getSampleCount()))
			.build());
		panelComponent.getChildren().add(LineComponent.builder()
			.left("Renderer")
			.right(shorten(snapshot.getRenderer()))
			.build());
		panelComponent.getChildren().add(LineComponent.builder()
			.left("OpenGL")
			.right(shorten(snapshot.getGlVersion()))
			.build());
		panelComponent.getChildren().add(LineComponent.builder()
			.left("Timer queries")
			.right(snapshot.isTimerQueriesSupported() ? "supported" : "unavailable")
			.rightColor(snapshot.isTimerQueriesSupported() ? Color.WHITE : UNAVAILABLE)
			.build());
		panelComponent.getChildren().add(LineComponent.builder()
			.left("Debug markers")
			.right(snapshot.isDebugMarkersEnabled() ? "enabled" : "unavailable")
			.rightColor(snapshot.isDebugMarkersEnabled() ? Color.WHITE : UNAVAILABLE)
			.build());
		if (snapshot.getUnavailableQueryCount() > 0 || snapshot.getDroppedQueryCount() > 0)
		{
			panelComponent.getChildren().add(LineComponent.builder()
				.left("Query misses")
				.right(snapshot.getUnavailableQueryCount() + " unavailable, " + snapshot.getDroppedQueryCount() + " dropped")
				.rightColor(UNAVAILABLE)
				.build());
		}

		addPhaseSection("CPU ms l/avg/p95/max", snapshot, true);
		addPhaseSection("GPU ms l/avg/p95/max", snapshot, false);
		addCounters(snapshot);

		return super.render(graphics);
	}

	private void addPhaseSection(String title, GpuProfilerSnapshot snapshot, boolean cpu)
	{
		panelComponent.getChildren().add(TitleComponent.builder()
			.text(title)
			.color(SECTION)
			.build());
		for (GpuProfilerPhase phase : GpuProfilerPhase.VALUES)
		{
			if (!cpu && !phase.isGpuTimed())
			{
				continue;
			}

			GpuProfilerSnapshot.PhaseStats stats = cpu ? snapshot.getCpuStats(phase) : snapshot.getGpuStats(phase);
			panelComponent.getChildren().add(LineComponent.builder()
				.left(phase.getDisplayName())
				.right(formatPhaseStats(stats))
				.rightColor(stats.isAvailable() ? Color.WHITE : UNAVAILABLE)
				.build());
		}
	}

	private void addCounters(GpuProfilerSnapshot snapshot)
	{
		panelComponent.getChildren().add(TitleComponent.builder()
			.text("Counters latest/avg/max")
			.color(SECTION)
			.build());
		addCounter(snapshot, GpuProfilerCounter.OPAQUE_ZONE_DRAWS);
		addCounter(snapshot, GpuProfilerCounter.ALPHA_ZONE_DRAWS);
		addCounter(snapshot, GpuProfilerCounter.DYNAMIC_MODELS);
		addCounter(snapshot, GpuProfilerCounter.TEMP_MODELS);
		addCounter(snapshot, GpuProfilerCounter.ZONES_REBUILT);
		addCounter(snapshot, GpuProfilerCounter.UPLOADED_BYTES);
	}

	private void addCounter(GpuProfilerSnapshot snapshot, GpuProfilerCounter counter)
	{
		GpuProfilerSnapshot.CounterStats stats = snapshot.getCounterStats(counter);
		panelComponent.getChildren().add(LineComponent.builder()
			.left(counter.getDisplayName())
			.right(formatCounterStats(stats))
			.build());
	}

	private static String formatPhaseStats(GpuProfilerSnapshot.PhaseStats stats)
	{
		if (!stats.isAvailable())
		{
			return "n/a";
		}

		return String.format(Locale.ROOT, "%.2f/%.2f/%.2f/%.2f (%d)",
			stats.getLatestNanos() / 1_000_000d,
			stats.getAverageNanos() / 1_000_000d,
			stats.getP95Nanos() / 1_000_000d,
			stats.getMaxNanos() / 1_000_000d,
			stats.getSampleCount());
	}

	private static String formatCounterStats(GpuProfilerSnapshot.CounterStats stats)
	{
		if (stats.getSampleCount() == 0)
		{
			return "0/0/0";
		}

		return String.format(Locale.ROOT, "%d/%.1f/%d",
			stats.getLatest(),
			stats.getAverage(),
			stats.getMax());
	}

	private static String shorten(String value)
	{
		if (value == null || value.length() <= 34)
		{
			return value;
		}

		return value.substring(0, 31) + "...";
	}
}
