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

import java.time.Clock;
import java.util.Arrays;
import java.util.Collections;
import java.util.EnumSet;
import java.util.Set;
import java.util.function.Consumer;
import net.runelite.api.WorldType;

/** State machine serialized by the plugin's lifecycle/event monitor. */
final class OfferRecorder
{
	static final int SLOTS = 8;
	private final String runId;
	private final Clock clock;
	private final Consumer<ObservationRecord> output;
	private final OfferSnapshot[] previous = new OfferSnapshot[SLOTS];
	private final String[] offerIds = new String[SLOTS];
	private final boolean[] observed = new boolean[SLOTS];
	private long sequence;
	private long intervals;
	private long offers;
	private String intervalId;
	private Integer world;
	private Integer environment;
	private Set<WorldType> worldTypes;

	OfferRecorder(String runId, Clock clock, Consumer<ObservationRecord> output)
	{
		this.runId = runId;
		this.clock = clock;
		this.output = output;
		emit("run_start", "enabled", null, null, null);
	}

	boolean isObserving()
	{
		return intervalId != null;
	}

	boolean matches(int world, int environment, Set<WorldType> types)
	{
		return isObserving() && this.world == world && this.environment == environment && worldTypes.equals(types);
	}

	void begin(int world, int environment, Set<WorldType> types)
	{
		this.world = world;
		this.environment = environment;
		EnumSet<WorldType> copy = EnumSet.noneOf(WorldType.class);
		copy.addAll(types);
		worldTypes = Collections.unmodifiableSet(copy);
		intervalId = runId + ":" + ++intervals;
		emit("interval_start", "snapshot_not_placement", null, null, null);
	}

	void observe(int slot, OfferSnapshot snapshot, String reason)
	{
		if (!isObserving() || slot < 0 || slot >= SLOTS)
		{
			return;
		}
		OfferSnapshot old = previous[slot];
		if (observed[slot] && java.util.Objects.equals(old, snapshot))
		{
			return;
		}
		observed[slot] = true;
		if (snapshot == null)
		{
			emit("slot_unavailable", reason, slot, offerIds[slot], null);
			offerIds[slot] = null;
		}
		else
		{
			if (!snapshot.isEmpty() && (old == null || !snapshot.canFollow(old)))
			{
				if (offerIds[slot] != null)
				{
					emit("offer_boundary", "slot_reuse_or_discontinuity", slot, offerIds[slot], null);
				}
				offerIds[slot] = intervalId + ":" + ++offers;
			}
			// An EMPTY observation may close the preceding episode, but is not cancellation.
			emit("offer_snapshot", reason, slot, offerIds[slot], snapshot);
			if (snapshot.isEmpty())
			{
				offerIds[slot] = null;
			}
		}
		previous[slot] = snapshot;
	}

	void heartbeat()
	{
		emit("heartbeat", "client_observation_only", null, null, null);
	}

	void gap(String reason)
	{
		if (isObserving())
		{
			emit("interval_end", reason, null, null, null);
		}
		intervalId = null;
		world = null;
		environment = null;
		worldTypes = null;
		Arrays.fill(previous, null);
		Arrays.fill(offerIds, null);
		Arrays.fill(observed, false);
	}

	void paused(String reason)
	{
		emit("observation_paused", reason, null, null, null);
	}

	void close()
	{
		gap("disabled");
		emit("run_end", "disabled", null, null, null);
	}

	private void emit(String type, String reason, Integer slot, String offerId, OfferSnapshot snapshot)
	{
		output.accept(new ObservationRecord(type, clock.instant().toString(), runId, ++sequence,
			intervalId, reason, world, environment, worldTypes, slot, offerId, snapshot));
	}
}
