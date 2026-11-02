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
package net.runelite.client.plugins.geofferrecorder;

import com.google.gson.Gson;
import java.time.Clock;
import java.util.EnumSet;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import javax.inject.Inject;
import javax.swing.JOptionPane;
import javax.swing.SwingUtilities;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.GrandExchangeOffer;
import net.runelite.api.WorldType;
import net.runelite.api.events.GameStateChanged;
import net.runelite.api.events.GameTick;
import net.runelite.api.events.GrandExchangeOfferChanged;
import net.runelite.client.RuneLite;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.events.RuneScapeProfileChanged;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;

@PluginDescriptor(
	name = "GE Offer Recorder",
	description = "Opt-in local JSONL observations of your own GE offers; no uploads or trading actions",
	tags = {"grand", "exchange", "local", "recording"},
	enabledByDefault = false
)
@Slf4j
public class GeOfferRecorderPlugin extends Plugin
{
	private static final long HEARTBEAT_NANOS = TimeUnit.SECONDS.toNanos(30);
	private static final long GAP_NANOS = TimeUnit.SECONDS.toNanos(75);
	private static final Set<WorldType> SUPPORTED_TYPES = EnumSet.of(WorldType.MEMBERS, WorldType.SKILL_TOTAL);

	@Inject
	private Client client;

	@Inject
	private Gson gson;

	private JsonlOfferWriter writer;
	private OfferRecorder recorder;
	private long lastTick;
	private long lastHeartbeat;
	private boolean unsupported;

	@Override
	protected synchronized void startUp()
	{
		String runId = UUID.randomUUID().toString();
		writer = createWriter(runId);
		recorder = new OfferRecorder(runId, Clock.systemUTC(), writer::accept);
		unsupported = false;
		// Snapshot on the next game tick, not from the lifecycle (Swing) thread or mid-login.
	}

	JsonlOfferWriter createWriter(String runId)
	{
		return new JsonlOfferWriter(RuneLite.RUNELITE_DIR.toPath().resolve("ge-offer-recorder"), runId, gson, reason ->
		{
			log.error("GE Offer Recorder stopped: {}. Observation continuity is lost; see OFFER_RECORDER.md.", reason);
			SwingUtilities.invokeLater(() -> JOptionPane.showMessageDialog(null,
				"GE Offer Recorder stopped: " + reason + ".\n"
					+ "Observations may be missing. Check disk space, permissions, and recorder limits.\n"
					+ "After fixing the cause, disable and re-enable the plugin to start a new recording.",
				"GE Offer Recorder", JOptionPane.ERROR_MESSAGE));
		});
	}

	@Override
	protected synchronized void shutDown()
	{
		if (recorder != null)
		{
			recorder.close();
			writer.close(); // Drains asynchronously; never wait for disk on the client/Swing thread.
			recorder = null;
			writer = null;
		}
	}

	@Subscribe
	public synchronized void onGameStateChanged(GameStateChanged event)
	{
		if (recorder != null && event.getGameState() != GameState.LOGGED_IN)
		{
			recorder.gap("game_state_" + event.getGameState().name());
		}
	}

	@Subscribe
	public synchronized void onRuneScapeProfileChanged(RuneScapeProfileChanged event)
	{
		if (recorder != null)
		{
			// Deliberately never inspect or store the profile/account identifiers in this event.
			recorder.gap("profile_changed");
		}
	}

	@Subscribe
	public synchronized void onGameTick(GameTick event)
	{
		if (recorder == null || client.getGameState() != GameState.LOGGED_IN)
		{
			return;
		}
		long now = nanoTime();
		checkBoundary(now);
		lastTick = now;
		if (!supportedWorld())
		{
			if (!unsupported)
			{
				recorder.paused("unsupported_world_or_environment");
				unsupported = true;
			}
			return;
		}
		unsupported = false;
		if (!recorder.isObserving())
		{
			recorder.begin(client.getWorld(), client.getEnvironment(), client.getWorldType());
			snapshot("initial_snapshot");
			recorder.heartbeat();
			lastHeartbeat = now;
		}
		else if (now - lastHeartbeat >= HEARTBEAT_NANOS)
		{
			snapshot("heartbeat_snapshot");
			recorder.heartbeat();
			lastHeartbeat = now;
		}
	}

	@Subscribe
	public synchronized void onGrandExchangeOfferChanged(GrandExchangeOfferChanged event)
	{
		if (recorder == null)
		{
			return;
		}
		checkBoundary(nanoTime());
		if (recorder.isObserving())
		{
			GrandExchangeOffer offer = event.getOffer();
			recorder.observe(event.getSlot(), offer == null ? null : OfferSnapshot.capture(offer), "offer_event");
		}
	}

	private void checkBoundary(long now)
	{
		if (!recorder.isObserving())
		{
			return;
		}
		if (client.getGameState() != GameState.LOGGED_IN)
		{
			recorder.gap("not_logged_in");
		}
		else if (!supportedWorld() || !recorder.matches(client.getWorld(), client.getEnvironment(), client.getWorldType()))
		{
			recorder.gap("world_or_environment_changed");
		}
		else if (now - lastTick > GAP_NANOS)
		{
			recorder.gap("client_tick_gap");
		}
	}

	private boolean supportedWorld()
	{
		Set<WorldType> types = client.getWorldType();
		return client.getEnvironment() == 0 && client.getWorld() > 0 && types != null && SUPPORTED_TYPES.containsAll(types);
	}

	private void snapshot(String reason)
	{
		GrandExchangeOffer[] offers = client.getGrandExchangeOffers();
		for (int slot = 0; slot < OfferRecorder.SLOTS; slot++)
		{
			GrandExchangeOffer offer = offers != null && slot < offers.length ? offers[slot] : null;
			recorder.observe(slot, offer == null ? null : OfferSnapshot.capture(offer), reason);
		}
	}

	long nanoTime()
	{
		return System.nanoTime();
	}
}
