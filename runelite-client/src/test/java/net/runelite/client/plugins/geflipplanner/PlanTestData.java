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

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;

final class PlanTestData
{
	static final Instant NOW = Instant.parse("2026-10-01T12:00:00Z");
	static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);

	private PlanTestData()
	{
	}

	static JsonObject snapshot()
	{
		return new JsonParser().parse("{"
			+ "\"schemaVersion\":1,\"mode\":\"snapshot\","
			+ "\"generatedAt\":\"2026-10-01T12:00:00Z\",\"asOf\":\"2026-10-01T11:59:00Z\","
			+ "\"expiresAt\":\"2026-10-01T12:05:00Z\","
			+ "\"bankrollGp\":10000000,\"cashReserveGp\":2000000,\"availableSlots\":6,"
			+ "\"sessionMinutes\":30,\"policy\":\"liquidity_margin\",\"accountLimitsVerified\":false,"
			+ "\"warnings\":[\"Quoted prices do not establish fills\"],"
			+ "\"candidates\":[{\"itemId\":4151,\"name\":\"Example item\",\"buyPrice\":100,"
			+ "\"sellPrice\":120,\"quantity\":10,\"capitalGp\":1000,"
			+ "\"taxPerItemGp\":2,\"netMarginPerItemGp\":18}]}"
		).getAsJsonObject();
	}

	static JsonObject historical()
	{
		JsonObject plan = snapshot();
		plan.addProperty("mode", "historical");
		plan.add("expiresAt", null);
		plan.addProperty("asOf", "2015-01-01T00:00:00Z");
		return plan;
	}

	static JsonObject candidate(JsonObject plan)
	{
		return plan.getAsJsonArray("candidates").get(0).getAsJsonObject();
	}

	static byte[] bytes(JsonObject plan)
	{
		return plan.toString().getBytes(StandardCharsets.UTF_8);
	}

	static FlipPlan parse(JsonObject plan) throws IOException
	{
		return FlipPlanParser.parse(bytes(plan), CLOCK);
	}
}
