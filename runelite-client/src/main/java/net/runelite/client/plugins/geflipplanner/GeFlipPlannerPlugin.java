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

import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.nio.file.Path;
import java.time.Clock;
import javax.inject.Inject;
import net.runelite.client.RuneLite;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;
import net.runelite.client.ui.ClientToolbar;
import net.runelite.client.ui.NavigationButton;

@PluginDescriptor(
	name = "GE Flip Planner",
	description = "Inspect manually loaded, local GE research plans; no trading automation",
	tags = {"grandexchange", "research", "panel"},
	enabledByDefault = false
)
public class GeFlipPlannerPlugin extends Plugin
{
	@Inject
	private ClientToolbar clientToolbar;

	private GeFlipPlannerPanel panel;
	private NavigationButton navigation;

	@Override
	protected void startUp()
	{
		// PluginManager starts and stops plugins on the EDT. No file is read here.
		Clock clock = Clock.systemUTC();
		Path path = RuneLite.RUNELITE_DIR.toPath().resolve("ge-flip-planner").resolve("plan.json");
		panel = new GeFlipPlannerPanel(clock, () -> FlipPlanLoader.load(path, clock));
		navigation = NavigationButton.builder()
			.tooltip("GE Flip Planner")
			.icon(createIcon())
			.priority(7)
			.panel(panel)
			.build();
		clientToolbar.addNavigation(navigation);
	}

	@Override
	protected void shutDown()
	{
		if (panel != null)
		{
			panel.close();
			panel = null;
		}
		if (navigation != null)
		{
			clientToolbar.removeNavigation(navigation);
			navigation = null;
		}
	}

	private static BufferedImage createIcon()
	{
		BufferedImage image = new BufferedImage(16, 16, BufferedImage.TYPE_INT_ARGB);
		Graphics2D graphics = image.createGraphics();
		try
		{
			graphics.setColor(new Color(240, 175, 60));
			graphics.drawRect(2, 1, 11, 13);
			graphics.fillRect(4, 8, 2, 4);
			graphics.fillRect(7, 5, 2, 7);
			graphics.fillRect(10, 3, 2, 9);
		}
		finally
		{
			graphics.dispose();
		}
		return image;
	}
}
