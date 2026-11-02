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

import lombok.Value;
import net.runelite.api.GrandExchangeOffer;
import net.runelite.api.GrandExchangeOfferState;

/** A value copy, never a live client offer reference. */
@Value
class OfferSnapshot
{
	int itemId;
	long price;
	int totalQuantity;
	int filledQuantity;
	long spent;
	GrandExchangeOfferState state;

	static OfferSnapshot capture(GrandExchangeOffer offer)
	{
		return new OfferSnapshot(offer.getItemId(), offer.getPrice(), offer.getTotalQuantity(),
			offer.getQuantitySold(), offer.getSpent(), offer.getState());
	}

	boolean isEmpty()
	{
		return state == GrandExchangeOfferState.EMPTY;
	}

	private boolean isBuy()
	{
		return state == GrandExchangeOfferState.BUYING || state == GrandExchangeOfferState.BOUGHT
			|| state == GrandExchangeOfferState.CANCELLED_BUY;
	}

	boolean canFollow(OfferSnapshot previous)
	{
		// IDs describe a locally observed offer episode, not a server offer identity.
		return !isEmpty() && !previous.isEmpty()
			&& (previous.state == GrandExchangeOfferState.BUYING || previous.state == GrandExchangeOfferState.SELLING)
			&& isBuy() == previous.isBuy() && itemId == previous.itemId && price == previous.price
			&& totalQuantity == previous.totalQuantity && filledQuantity >= previous.filledQuantity
			&& spent >= previous.spent;
	}
}
