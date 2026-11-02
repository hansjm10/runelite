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
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;
import net.runelite.api.GrandExchangeOffer;
import net.runelite.api.GrandExchangeOfferState;
import net.runelite.api.WorldType;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;
import org.junit.Before;
import org.junit.Test;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

public class OfferRecorderTest
{
	private final Gson gson = new Gson();
	private final List<JsonObject> records = new ArrayList<>();
	private OfferRecorder recorder;

	@Before
	public void setUp()
	{
		recorder = new OfferRecorder("run", Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC),
			r -> records.add(gson.toJsonTree(r).getAsJsonObject()));
		recorder.begin(301, 0, EnumSet.of(WorldType.MEMBERS));
	}

	@Test
	public void immutableSnapshotDedupAndLongValues()
	{
		GrandExchangeOffer live = mock(GrandExchangeOffer.class);
		when(live.getItemId()).thenReturn(4151);
		when(live.getPrice()).thenReturn(3_000_000_000L);
		when(live.getTotalQuantity()).thenReturn(10);
		when(live.getQuantitySold()).thenReturn(2);
		when(live.getSpent()).thenReturn(6_000_000_000L);
		when(live.getState()).thenReturn(GrandExchangeOfferState.BUYING);
		OfferSnapshot captured = OfferSnapshot.capture(live);
		when(live.getQuantitySold()).thenReturn(8);
		recorder.observe(0, captured, "offer_event");
		recorder.observe(0, captured, "offer_event");
		assertEquals(3, records.size());
		JsonObject record = last();
		assertEquals("2026-01-01T00:00:00Z", record.get("observedAt").getAsString());
		assertEquals(301, record.get("world").getAsInt());
		assertEquals(0, record.get("environment").getAsInt());
		assertEquals("MEMBERS", record.getAsJsonArray("worldTypes").get(0).getAsString());
		assertEquals(2, record.getAsJsonObject("offer").get("filledQuantity").getAsInt());
		assertEquals(3_000_000_000L, record.getAsJsonObject("offer").get("price").getAsLong());
		assertEquals(6_000_000_000L, record.getAsJsonObject("offer").get("spent").getAsLong());
	}

	@Test
	public void partialFillsCompletionAndCancellationAreRawStates()
	{
		recorder.observe(0, offer(GrandExchangeOfferState.BUYING, 0), "initial_snapshot");
		String id = id();
		recorder.observe(0, offer(GrandExchangeOfferState.BUYING, 3), "offer_event");
		assertEquals(id, id());
		recorder.observe(0, offer(GrandExchangeOfferState.BOUGHT, 10), "offer_event");
		assertEquals(id, id());
		assertEquals("BOUGHT", last().getAsJsonObject("offer").get("state").getAsString());
		recorder.observe(1, offer(GrandExchangeOfferState.SELLING, 0), "offer_event");
		String sell = id();
		recorder.observe(1, offer(GrandExchangeOfferState.SELLING, 4), "offer_event");
		recorder.observe(1, offer(GrandExchangeOfferState.CANCELLED_SELL, 4), "offer_event");
		assertEquals(sell, id());
		assertEquals("CANCELLED_SELL", last().getAsJsonObject("offer").get("state").getAsString());
		assertFalse(last().has("fillTime"));
	}

	@Test
	public void emptyTerminalReuseRepriceAndCounterRegressionBreakIdentity()
	{
		OfferSnapshot active = offer(GrandExchangeOfferState.BUYING, 3);
		recorder.observe(0, active, "offer_event");
		String first = id();
		recorder.observe(0, offer(GrandExchangeOfferState.EMPTY, 0), "offer_event");
		assertEquals(first, id());
		recorder.observe(0, active, "offer_event");
		assertNotEquals(first, id());
		String second = id();
		recorder.observe(0, offer(GrandExchangeOfferState.CANCELLED_BUY, 3), "offer_event");
		assertEquals(second, id());
		recorder.observe(0, active, "offer_event");
		assertNotEquals(second, id());
		assertEquals("offer_boundary", records.get(records.size() - 2).get("type").getAsString());
		String third = id();
		recorder.observe(0, offer(GrandExchangeOfferState.BUYING, 1), "offer_event");
		assertNotEquals(third, id());
		String fourth = id();
		recorder.observe(0, new OfferSnapshot(4151, 101, 10, 1, 100, GrandExchangeOfferState.BUYING), "offer_event");
		assertNotEquals(fourth, id());
	}

	@Test
	public void gapsAndUnavailableSlotsNeverJoinEpisodes()
	{
		OfferSnapshot active = offer(GrandExchangeOfferState.BUYING, 3);
		recorder.observe(0, active, "initial_snapshot");
		String first = id();
		recorder.gap("game_state_HOPPING");
		assertEquals("interval_end", last().get("type").getAsString());
		recorder.observe(0, active, "offer_event");
		assertEquals("interval_end", last().get("type").getAsString());
		recorder.begin(302, 0, EnumSet.noneOf(WorldType.class));
		recorder.observe(0, active, "initial_snapshot");
		assertNotEquals(first, id());
		String second = id();
		recorder.observe(0, null, "heartbeat_snapshot");
		assertEquals("slot_unavailable", last().get("type").getAsString());
		recorder.observe(0, active, "offer_event");
		assertNotEquals(second, id());
		recorder.heartbeat();
		assertEquals("heartbeat", last().get("type").getAsString());
		recorder.close();
		assertEquals("run_end", last().get("type").getAsString());
		for (int i = 0; i < records.size(); i++)
		{
			assertEquals(i + 1, records.get(i).get("sequence").getAsInt());
		}
		assertTrue(records.stream().noneMatch(r -> r.has("username") || r.has("accountHash")));
	}

	private static OfferSnapshot offer(GrandExchangeOfferState state, int filled)
	{
		return new OfferSnapshot(4151, 100, 10, filled, filled * 100L, state);
	}

	private JsonObject last()
	{
		return records.get(records.size() - 1);
	}

	private String id()
	{
		return last().get("offerId").getAsString();
	}
}
