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

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.CLOCK;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.NOW;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.bytes;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.candidate;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.historical;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.parse;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.snapshot;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;
import org.junit.Test;

public class FlipPlanParserTest
{
	@Test
	public void acceptsPythonProducerContractFixtures() throws Exception
	{
		Clock clock = Clock.fixed(Instant.parse("2026-11-02T21:01:00Z"), ZoneOffset.UTC);
		for (String mode : new String[]{"historical", "snapshot"})
		{
			try (InputStream stream = getClass().getResourceAsStream("producer-" + mode + "-plan.json"))
			{
				assertNotNull(stream);
				FlipPlan plan = FlipPlanParser.parse(FlipPlanLoader.readBounded(stream), clock);
				assertEquals(mode, plan.getMode());
				assertEquals(1, plan.getCandidates().size());
				assertEquals(1000000, plan.getCandidates().get(0).getCapitalGp());
				assertEquals(940, plan.getCandidates().get(0).getNetMarginPerItemGp());
				assertFalse(plan.isExpired(clock.instant()));
			}
		}
	}

	@Test
	public void validSnapshot() throws Exception
	{
		FlipPlan plan = parse(snapshot());
		assertFalse(plan.isHistorical());
		assertFalse(plan.isExpired(NOW));
		assertEquals(1, plan.getCandidates().size());
		assertEquals(1000, plan.getCandidates().get(0).getCapitalGp());
		assertEquals(18, plan.getCandidates().get(0).getNetMarginPerItemGp());
		assertEquals(30, plan.getSessionMinutes());
	}

	@Test
	public void oldHistoricalPlanRemainsInspectable() throws Exception
	{
		FlipPlan plan = parse(historical());
		assertTrue(plan.isHistorical());
		assertFalse(plan.isExpired(NOW.plusSeconds(1000000)));
		assertEquals(1, plan.getCandidates().size());
	}

	@Test
	public void staleSnapshotIsRecognizableAtExactExpiry() throws Exception
	{
		FlipPlan plan = parse(snapshot());
		assertFalse(plan.isExpired(NOW.plusSeconds(299)));
		assertTrue(plan.isExpired(NOW.plusSeconds(300)));
		assertTrue(FlipPlanParser.parse(bytes(snapshot()), Clock.fixed(NOW.plusSeconds(301), ZoneOffset.UTC))
			.isExpired(NOW.plusSeconds(301)));
	}

	@Test
	public void emptyCandidatesAndZeroSlotsAreValid() throws Exception
	{
		JsonObject plan = snapshot();
		plan.add("candidates", new JsonArray());
		plan.addProperty("availableSlots", 0);
		plan.addProperty("cashReserveGp", 10000000);
		assertTrue(parse(plan).getCandidates().isEmpty());
	}

	@Test
	public void everyRequiredRootFieldMustExist() throws Exception
	{
		for (String field : new ArrayList<>(snapshot().keySet()))
		{
			JsonObject plan = snapshot();
			plan.remove(field);
			reject(plan);
		}
	}

	@Test
	public void everyRequiredCandidateFieldMustExist() throws Exception
	{
		for (String field : new ArrayList<>(candidate(snapshot()).keySet()))
		{
			JsonObject plan = snapshot();
			candidate(plan).remove(field);
			reject(plan);
		}
	}

	@Test
	public void wrongRootTypesAndNullAreRejected() throws Exception
	{
		for (String field : new ArrayList<>(snapshot().keySet()))
		{
			JsonObject plan = snapshot();
			plan.add(field, null);
			reject(plan);
			plan.add(field, new JsonObject());
			reject(plan);
		}
	}

	@Test
	public void wrongCandidateTypesAndNullAreRejected() throws Exception
	{
		for (String field : new ArrayList<>(candidate(snapshot()).keySet()))
		{
			JsonObject plan = snapshot();
			candidate(plan).add(field, null);
			reject(plan);
			candidate(plan).add(field, new JsonArray());
			reject(plan);
		}
	}

	@Test
	public void stringsAndFractionsDoNotCoerceToIntegers() throws Exception
	{
		String[] rootFields = {"schemaVersion", "bankrollGp", "cashReserveGp", "availableSlots", "sessionMinutes"};
		for (String field : rootFields)
		{
			JsonObject plan = snapshot();
			plan.addProperty(field, "1");
			reject(plan);
			plan.addProperty(field, new BigDecimal("1.5"));
			reject(plan);
		}
		for (String field : candidate(snapshot()).keySet())
		{
			if (field.equals("name"))
			{
				continue;
			}
			JsonObject plan = snapshot();
			candidate(plan).addProperty(field, "1");
			reject(plan);
			candidate(plan).addProperty(field, new BigDecimal("1.5"));
			reject(plan);
		}
	}

	@Test
	public void mathematicallyExactIntegerNotationIsAccepted() throws Exception
	{
		JsonObject plan = snapshot();
		candidate(plan).addProperty("quantity", new BigDecimal("1e1"));
		assertEquals(10, parse(plan).getCandidates().get(0).getQuantity());
	}

	@Test
	public void numericBoundsAreChecked() throws Exception
	{
		rejectRoot("bankrollGp", new JsonPrimitive(0));
		rejectRoot("cashReserveGp", new JsonPrimitive(-1));
		rejectRoot("cashReserveGp", new JsonPrimitive(10000001));
		rejectRoot("availableSlots", new JsonPrimitive(-1));
		rejectRoot("availableSlots", new JsonPrimitive(9));
		rejectRoot("sessionMinutes", new JsonPrimitive(0));
		rejectRoot("sessionMinutes", new JsonPrimitive(2147483648L));
		for (String field : candidate(snapshot()).keySet())
		{
			if (field.equals("name"))
			{
				continue;
			}
			rejectCandidate(field, new JsonPrimitive(-1));
			if (!field.equals("taxPerItemGp"))
			{
				rejectCandidate(field, new JsonPrimitive(0));
			}
		}
		rejectCandidate("itemId", new JsonPrimitive(2147483648L));
		rejectCandidate("quantity", new JsonPrimitive(2147483648L));
		rejectCandidate("buyPrice", new JsonPrimitive(new BigDecimal("9223372036854775808")));
		rejectCandidate("quantity", new JsonPrimitive(new BigDecimal("1e999999")));
	}

	@Test
	public void unknownSchemaModePolicyAndVerifiedLimitsRejected() throws Exception
	{
		rejectRoot("schemaVersion", new JsonPrimitive(2));
		rejectRoot("mode", new JsonPrimitive("live"));
		rejectRoot("policy", new JsonPrimitive("unknown"));
		rejectRoot("accountLimitsVerified", new JsonPrimitive(true));
		rejectRoot("accountLimitsVerified", new JsonPrimitive("false"));
		JsonObject plan = snapshot();
		plan.addProperty("policy", "chronos_guard");
		assertEquals("chronos_guard", parse(plan).getPolicy());
	}

	@Test
	public void capitalAndMarginMustMatchExactly() throws Exception
	{
		rejectCandidate("capitalGp", new JsonPrimitive(999));
		rejectCandidate("netMarginPerItemGp", new JsonPrimitive(19));
		rejectCandidate("taxPerItemGp", new JsonPrimitive(120));
	}

	@Test
	public void multiplicationAndSubtractionOverflowRejected() throws Exception
	{
		JsonObject plan = snapshot();
		candidate(plan).addProperty("buyPrice", Long.MAX_VALUE);
		reject(plan);
		candidate(plan).addProperty("quantity", 1);
		candidate(plan).addProperty("capitalGp", Long.MAX_VALUE);
		candidate(plan).addProperty("sellPrice", 1);
		candidate(plan).addProperty("taxPerItemGp", Long.MAX_VALUE);
		reject(plan);
	}

	@Test
	public void totalCapitalOverflowRejected() throws Exception
	{
		JsonObject plan = snapshot();
		plan.addProperty("bankrollGp", Long.MAX_VALUE);
		plan.addProperty("cashReserveGp", 0);
		JsonObject first = candidate(plan);
		long capital = Long.MAX_VALUE / 2 + 1;
		first.addProperty("buyPrice", capital);
		first.addProperty("quantity", 1);
		first.addProperty("capitalGp", capital);
		first.addProperty("sellPrice", capital + 1);
		first.addProperty("taxPerItemGp", 0);
		first.addProperty("netMarginPerItemGp", 1);
		JsonObject second = first.deepCopy();
		second.addProperty("itemId", 2);
		plan.getAsJsonArray("candidates").add(second);
		reject(plan);
	}

	@Test
	public void totalCapitalRespectsReserve() throws Exception
	{
		JsonObject plan = snapshot();
		plan.addProperty("bankrollGp", 2001000);
		assertNotNull(parse(plan));
		plan.addProperty("bankrollGp", 2000999);
		reject(plan);
	}

	@Test
	public void duplicateItemsAndExcessSlotsRejected() throws Exception
	{
		JsonObject plan = snapshot();
		plan.getAsJsonArray("candidates").add(candidate(plan).deepCopy());
		reject(plan);
		plan = snapshot();
		plan.addProperty("availableSlots", 0);
		reject(plan);
		plan = snapshot();
		plan.addProperty("availableSlots", 8);
		for (int i = 2; i <= 7; i++)
		{
			JsonObject extra = candidate(plan).deepCopy();
			extra.addProperty("itemId", i);
			plan.getAsJsonArray("candidates").add(extra);
		}
		reject(plan);
		plan.getAsJsonArray("candidates").remove(6);
		assertEquals(6, parse(plan).getCandidates().size());
	}

	@Test
	public void timestampBoundsAndUtcAreChecked() throws Exception
	{
		rejectRoot("generatedAt", new JsonPrimitive(NOW.plusSeconds(61).toString()));
		JsonObject plan = snapshot();
		plan.addProperty("generatedAt", NOW.plusSeconds(60).toString());
		assertNotNull(parse(plan));
		rejectRoot("asOf", new JsonPrimitive(NOW.plusSeconds(1).toString()));
		rejectRoot("asOf", new JsonPrimitive("yesterday"));
		rejectRoot("asOf", new JsonPrimitive("2026-10-01T11:59:00+01:00"));
		rejectRoot("expiresAt", new JsonPrimitive(NOW.toString()));
		rejectRoot("expiresAt", new JsonPrimitive(NOW.plusSeconds(301).toString()));
		plan = snapshot();
		plan.addProperty("asOf", NOW.minusSeconds(601).toString());
		reject(plan);
		plan.addProperty("asOf", NOW.minusSeconds(600).toString());
		assertNotNull(parse(plan));
		plan = historical();
		plan.addProperty("expiresAt", NOW.plusSeconds(1).toString());
		reject(plan);
	}

	@Test
	public void malformedAndHugeStringsAndListsRejected() throws Exception
	{
		rejectCandidate("name", new JsonPrimitive(" "));
		rejectCandidate("name", new JsonPrimitive("x".repeat(121)));
		rejectCandidate("name", new JsonPrimitive("bad\u0001name"));
		reject(snapshot().toString().replace("Example item", "\\ud800").getBytes(StandardCharsets.UTF_8));
		reject(snapshot().toString().replace("Example item", "\\udc00").getBytes(StandardCharsets.UTF_8));
		JsonObject plan = snapshot();
		plan.getAsJsonArray("warnings").add("x".repeat(513));
		reject(plan);
		plan = snapshot();
		for (int i = 0; i < 32; i++)
		{
			plan.getAsJsonArray("warnings").add("warning");
		}
		reject(plan);
		plan = snapshot();
		plan.getAsJsonArray("warnings").add(123);
		reject(plan);
	}

	@Test
	public void htmlLikeTextIsPreservedLiterally() throws Exception
	{
		JsonObject plan = snapshot();
		candidate(plan).addProperty("name", "<html><b>Example</b></html>");
		assertEquals("<html><b>Example</b></html>", parse(plan).getCandidates().get(0).getName());
	}

	@Test
	public void strictJsonRejectsDuplicatesCommentsTrailingDataAndNesting() throws Exception
	{
		String valid = snapshot().toString();
		for (String invalid : new String[]{"", "[]", "null", "{", valid + "{}", "/*comment*/" + valid,
			valid.replace("\"schemaVersion\":1", "\"schemaVersion\":1,\"schemaVersion\":1"),
			valid.replace("\"schemaVersion\":1", "schemaVersion:1"), "[".repeat(1000)})
		{
			reject(invalid.getBytes(StandardCharsets.UTF_8));
		}
	}

	@Test
	public void invalidUtf8AndOversizeInputRejected() throws Exception
	{
		reject(new byte[]{(byte) 0xc3, (byte) 0x28});
		reject(new byte[FlipPlanParser.MAX_BYTES + 1]);
	}

	private static void rejectRoot(String field, JsonElement value) throws Exception
	{
		JsonObject plan = snapshot();
		plan.add(field, value);
		reject(plan);
	}

	private static void rejectCandidate(String field, JsonElement value) throws Exception
	{
		JsonObject plan = snapshot();
		candidate(plan).add(field, value);
		reject(plan);
	}

	private static void reject(JsonObject plan) throws Exception
	{
		reject(bytes(plan));
	}

	private static void reject(byte[] input) throws Exception
	{
		try
		{
			FlipPlanParser.parse(input, CLOCK);
			fail("Expected invalid plan rejection");
		}
		catch (IOException expected)
		{
			assertNotNull(expected.getMessage());
		}
	}
}
