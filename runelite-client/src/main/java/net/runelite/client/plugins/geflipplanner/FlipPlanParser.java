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
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import com.google.gson.stream.JsonReader;
import com.google.gson.stream.JsonToken;
import java.io.IOException;
import java.io.StringReader;
import java.math.BigDecimal;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.DateTimeException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

final class FlipPlanParser
{
	static final int MAX_BYTES = 256 * 1024;
	static final int MAX_WARNINGS = 32;
	static final int MAX_TEXT_LENGTH = 512;
	static final int MAX_NAME_LENGTH = 120;

	private FlipPlanParser()
	{
	}

	static FlipPlan parse(byte[] bytes, Clock clock) throws IOException
	{
		require(bytes.length <= MAX_BYTES, "Plan exceeds 256 KiB");
		String text = StandardCharsets.UTF_8.newDecoder()
			.onMalformedInput(CodingErrorAction.REPORT)
			.onUnmappableCharacter(CodingErrorAction.REPORT)
			.decode(ByteBuffer.wrap(bytes)).toString();
		try (JsonReader reader = new JsonReader(new StringReader(text)))
		{
			reader.setLenient(false);
			JsonElement root = readValue(reader, 0);
			require(reader.peek() == JsonToken.END_DOCUMENT, "Trailing JSON data");
			require(root.isJsonObject(), "Plan must be an object");
			return validate(root.getAsJsonObject(), clock.instant());
		}
		catch (IllegalArgumentException | ArithmeticException | DateTimeException | IllegalStateException ex)
		{
			throw new IOException("Invalid plan value", ex);
		}
	}

	// Gson's tree parser is lenient and recursive. Read a strictly bounded tree instead,
	// rejecting duplicate keys and excess nesting before they can hide malformed input.
	private static JsonElement readValue(JsonReader reader, int depth) throws IOException
	{
		require(depth <= 3, "Excessive JSON nesting");
		switch (reader.peek())
		{
			case BEGIN_OBJECT:
				JsonObject object = new JsonObject();
				reader.beginObject();
				while (reader.hasNext())
				{
					require(object.size() < 16, "Too many object fields");
					String key = reader.nextName();
					require(key.length() <= 40 && !object.has(key), "Invalid or duplicate field");
					object.add(key, readValue(reader, depth + 1));
				}
				reader.endObject();
				return object;
			case BEGIN_ARRAY:
				JsonArray array = new JsonArray();
				reader.beginArray();
				while (reader.hasNext())
				{
					require(array.size() < MAX_WARNINGS, "Too many list entries");
					array.add(readValue(reader, depth + 1));
				}
				reader.endArray();
				return array;
			case STRING:
				String value = reader.nextString();
				require(value.length() <= MAX_TEXT_LENGTH, "Text too long");
				return new JsonPrimitive(value);
			case NUMBER:
				String number = reader.nextString();
				require(number.length() <= 64, "Number too long");
				return new JsonPrimitive(new BigDecimal(number));
			case BOOLEAN:
				return new JsonPrimitive(reader.nextBoolean());
			case NULL:
				reader.nextNull();
				return JsonNull.INSTANCE;
			default:
				throw new IOException("Invalid JSON value");
		}
	}

	private static FlipPlan validate(JsonObject root, Instant now) throws IOException
	{
		require(integer(root, "schemaVersion", 1, 1) == 1, "Unknown schema");
		String mode = string(root, "mode", 10);
		require(mode.equals("historical") || mode.equals("snapshot"), "Unknown mode");
		Instant generated = instant(root, "generatedAt");
		Instant asOf = instant(root, "asOf");
		require(!generated.isAfter(now.plusSeconds(60)), "Plan generated in the future");
		require(!asOf.isAfter(generated), "asOf is after generatedAt");
		JsonElement expiry = required(root, "expiresAt");
		Instant expires = null;
		if (mode.equals("historical"))
		{
			require(expiry.isJsonNull(), "Historical plans must not expire");
		}
		else
		{
			expires = instant(root, "expiresAt");
			require(expires.isAfter(generated)
				&& !expires.isAfter(generated.plusSeconds(300))
				&& !expires.isAfter(asOf.plusSeconds(900)), "Invalid snapshot expiry");
		}
		long bankroll = integer(root, "bankrollGp", 1, Long.MAX_VALUE);
		long reserve = integer(root, "cashReserveGp", 0, bankroll);
		int slots = (int) integer(root, "availableSlots", 0, 8);
		int minutes = (int) integer(root, "sessionMinutes", 1, Integer.MAX_VALUE);
		String policy = string(root, "policy", 32);
		require(policy.equals("liquidity_margin") || policy.equals("chronos_guard"), "Unknown policy");
		JsonElement verified = required(root, "accountLimitsVerified");
		require(verified.isJsonPrimitive() && verified.getAsJsonPrimitive().isBoolean()
			&& !verified.getAsBoolean(), "Account limits must be marked unverified");
		List<String> warnings = new ArrayList<>();
		for (JsonElement warning : array(root, "warnings"))
		{
			warnings.add(plainString(warning, MAX_TEXT_LENGTH));
		}
		JsonArray items = array(root, "candidates");
		require(items.size() <= 6 && items.size() <= slots, "Too many candidates for slots");
		List<FlipPlan.Candidate> candidates = new ArrayList<>();
		Set<Integer> ids = new HashSet<>();
		long totalCapital = 0;
		for (JsonElement item : items)
		{
			require(item.isJsonObject(), "Candidate must be an object");
			JsonObject candidate = item.getAsJsonObject();
			int id = (int) integer(candidate, "itemId", 1, Integer.MAX_VALUE);
			require(ids.add(id), "Duplicate itemId");
			String name = string(candidate, "name", MAX_NAME_LENGTH);
			long buy = integer(candidate, "buyPrice", 1, Long.MAX_VALUE);
			long sell = integer(candidate, "sellPrice", 1, Long.MAX_VALUE);
			int quantity = (int) integer(candidate, "quantity", 1, Integer.MAX_VALUE);
			long capital = integer(candidate, "capitalGp", 1, Long.MAX_VALUE);
			long tax = integer(candidate, "taxPerItemGp", 0, Long.MAX_VALUE);
			long margin = integer(candidate, "netMarginPerItemGp", 1, Long.MAX_VALUE);
			require(capital == Math.multiplyExact(buy, quantity), "Capital does not match buy price and quantity");
			require(margin == Math.subtractExact(Math.subtractExact(sell, buy), tax), "Quoted margin mismatch");
			totalCapital = Math.addExact(totalCapital, capital);
			require(totalCapital <= bankroll - reserve, "Capital exceeds cash budget");
			candidates.add(new FlipPlan.Candidate(id, name, buy, sell, quantity, capital, tax, margin));
		}
		return new FlipPlan(mode, generated, asOf, expires, bankroll, reserve, slots, minutes, policy,
			List.copyOf(warnings), List.copyOf(candidates));
	}

	private static JsonElement required(JsonObject object, String key) throws IOException
	{
		JsonElement value = object.get(key);
		require(value != null, "Missing field: " + key);
		return value;
	}

	private static JsonArray array(JsonObject object, String key) throws IOException
	{
		JsonElement value = required(object, key);
		require(value.isJsonArray(), "Expected list: " + key);
		return value.getAsJsonArray();
	}

	private static long integer(JsonObject object, String key, long min, long max) throws IOException
	{
		JsonElement value = required(object, key);
		require(value.isJsonPrimitive() && value.getAsJsonPrimitive().isNumber(), "Expected integer: " + key);
		long number = value.getAsBigDecimal().longValueExact();
		require(number >= min && number <= max, "Out of range: " + key);
		return number;
	}

	private static String string(JsonObject object, String key, int maxLength) throws IOException
	{
		return plainString(required(object, key), maxLength);
	}

	private static String plainString(JsonElement value, int maxLength) throws IOException
	{
		require(value.isJsonPrimitive() && value.getAsJsonPrimitive().isString(), "Expected text");
		String text = value.getAsString();
		require(!text.trim().isEmpty() && text.length() <= maxLength, "Invalid text length");
		for (int i = 0; i < text.length(); i++)
		{
			char ch = text.charAt(i);
			require(!Character.isISOControl(ch), "Control character in text");
			if (Character.isHighSurrogate(ch))
			{
				require(++i < text.length() && Character.isLowSurrogate(text.charAt(i)), "Malformed Unicode");
			}
			else
			{
				require(!Character.isLowSurrogate(ch), "Malformed Unicode");
			}
		}
		return text;
	}

	private static Instant instant(JsonObject object, String key) throws IOException
	{
		String value = string(object, key, 40);
		require(value.endsWith("Z"), "Expected UTC instant: " + key);
		return Instant.parse(value);
	}

	private static void require(boolean condition, String message) throws IOException
	{
		if (!condition)
		{
			throw new IOException(message);
		}
	}
}
