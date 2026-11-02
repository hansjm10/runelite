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
import com.google.gson.JsonObject;
import com.google.inject.Guice;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.GrandExchangeOffer;
import net.runelite.api.GrandExchangeOfferState;
import net.runelite.api.WorldType;
import net.runelite.api.events.GameStateChanged;
import net.runelite.api.events.GameTick;
import net.runelite.api.events.GrandExchangeOfferChanged;
import net.runelite.client.events.RuneScapeProfileChanged;
import net.runelite.client.plugins.PluginDescriptor;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

public class GeOfferRecorderPluginTest
{
	@Rule
	public TemporaryFolder temporary = new TemporaryFolder();

	private final Client client = mock(Client.class);
	private final Gson gson = new Gson();
	private final List<Runnable> tasks = new ArrayList<>();
	private final List<String> failures = new ArrayList<>();
	private Path output;
	private long now = 1;
	private GeOfferRecorderPlugin plugin;
	private GrandExchangeOffer offer;

	@Before
	public void setUp()
	{
		plugin = new GeOfferRecorderPlugin()
		{
			@Override
			JsonlOfferWriter createWriter(String runId)
			{
				output = temporary.getRoot().toPath().resolve("ge-offers-" + runId + ".jsonl");
				return new JsonlOfferWriter(temporary.getRoot().toPath(), runId, gson, failures::add,
					tasks::add, 256, 65536, 131072, 10);
			}

			@Override
			long nanoTime()
			{
				return now;
			}
		};
		Guice.createInjector(binder ->
		{
			binder.bind(Client.class).toInstance(client);
			binder.bind(Gson.class).toInstance(gson);
		}).injectMembers(plugin);
		when(client.getGameState()).thenReturn(GameState.LOGGED_IN);
		when(client.getWorld()).thenReturn(301);
		when(client.getWorldType()).thenReturn(EnumSet.of(WorldType.MEMBERS));
		offer = mock(GrandExchangeOffer.class);
		when(offer.getState()).thenReturn(GrandExchangeOfferState.BUYING);
		when(offer.getItemId()).thenReturn(4151);
		when(offer.getPrice()).thenReturn(100L);
		when(offer.getTotalQuantity()).thenReturn(10);
		when(client.getGrandExchangeOffers()).thenReturn(new GrandExchangeOffer[]{offer});
		plugin.startUp();
	}

	@Test
	public void disabledByDefaultEnableSnapshotAndPeriodicHeartbeat() throws Exception
	{
		assertFalse(GeOfferRecorderPlugin.class.getAnnotation(PluginDescriptor.class).enabledByDefault());
		plugin.onGameTick(new GameTick());
		changed(); // Duplicate observation.
		now += TimeUnit.SECONDS.toNanos(29);
		plugin.onGameTick(new GameTick());
		now += TimeUnit.SECONDS.toNanos(1);
		plugin.onGameTick(new GameTick());
		List<JsonObject> records = finish();
		assertEquals(1, ofType(records, "offer_snapshot").size());
		assertEquals(2, ofType(records, "heartbeat").size());
		assertEquals(7, ofType(records, "slot_unavailable").size());
		assertEquals("run_end", records.get(records.size() - 1).get("type").getAsString());
	}

	@Test
	public void loginHopDisconnectProfileAndLongTickGapsResetIds() throws Exception
	{
		state(GameState.LOGGING_IN);
		changed();
		state(GameState.LOGGED_IN);
		plugin.onGameTick(new GameTick());
		state(GameState.HOPPING);
		when(offer.getState()).thenReturn(GrandExchangeOfferState.EMPTY);
		changed(); // Client reset must not look like collection/cancellation.
		when(offer.getState()).thenReturn(GrandExchangeOfferState.BUYING);
		state(GameState.LOGGED_IN);
		plugin.onGameTick(new GameTick());
		state(GameState.CONNECTION_LOST);
		state(GameState.LOGGED_IN);
		plugin.onGameTick(new GameTick());
		plugin.onRuneScapeProfileChanged(new RuneScapeProfileChanged("private-old", "private-new"));
		plugin.onGameTick(new GameTick());
		now += TimeUnit.SECONDS.toNanos(76);
		plugin.onGameTick(new GameTick());
		List<JsonObject> records = finish();
		List<JsonObject> snapshots = ofType(records, "offer_snapshot");
		assertEquals(5, snapshots.size());
		assertEquals(5, snapshots.stream().map(r -> r.get("offerId").getAsString()).distinct().count());
		assertEquals(5, ofType(records, "interval_end").size());
		assertFalse(gson.toJson(records).contains("private-"));
		assertTrue(snapshots.stream().allMatch(r -> r.getAsJsonObject("offer").get("state").getAsString().equals("BUYING")));
	}

	@Test
	public void unsupportedEconomiesDoNotRecordOffers() throws Exception
	{
		when(client.getWorldType()).thenReturn(EnumSet.of(WorldType.MEMBERS, WorldType.DEADMAN));
		plugin.onGameTick(new GameTick());
		changed();
		when(client.getWorldType()).thenReturn(EnumSet.of(WorldType.SEASONAL));
		plugin.onGameTick(new GameTick());
		when(client.getWorldType()).thenReturn(EnumSet.of(WorldType.FRESH_START_WORLD));
		plugin.onGameTick(new GameTick());
		when(client.getWorldType()).thenReturn(EnumSet.of(WorldType.MEMBERS));
		when(client.getEnvironment()).thenReturn(1);
		plugin.onGameTick(new GameTick());
		List<JsonObject> records = finish();
		assertEquals(0, ofType(records, "offer_snapshot").size());
		assertEquals(1, ofType(records, "observation_paused").size());
	}

	@Test
	public void worldChangeWithoutStateEventStillBreaksContinuity() throws Exception
	{
		plugin.onGameTick(new GameTick());
		when(client.getWorld()).thenReturn(302);
		changed();
		plugin.onGameTick(new GameTick());
		when(client.getWorldType()).thenReturn(EnumSet.of(WorldType.BETA_WORLD));
		changed();
		plugin.onGameTick(new GameTick());
		List<JsonObject> records = finish();
		assertEquals(2, ofType(records, "offer_snapshot").size());
		assertEquals(2, ofType(records, "interval_start").size());
		assertEquals(2, ofType(records, "interval_end").size());
	}

	private void state(GameState state)
	{
		when(client.getGameState()).thenReturn(state);
		GameStateChanged event = new GameStateChanged();
		event.setGameState(state);
		plugin.onGameStateChanged(event);
	}

	private void changed()
	{
		GrandExchangeOfferChanged event = new GrandExchangeOfferChanged();
		event.setSlot(0);
		event.setOffer(offer);
		plugin.onGrandExchangeOfferChanged(event);
	}

	private List<JsonObject> finish() throws Exception
	{
		plugin.shutDown();
		tasks.forEach(Runnable::run);
		assertTrue(failures.isEmpty());
		return Files.readAllLines(output, StandardCharsets.UTF_8).stream()
			.map(line -> gson.fromJson(line, JsonObject.class)).collect(Collectors.toList());
	}

	private static List<JsonObject> ofType(List<JsonObject> records, String type)
	{
		return records.stream().filter(r -> r.get("type").getAsString().equals(type)).collect(Collectors.toList());
	}
}
