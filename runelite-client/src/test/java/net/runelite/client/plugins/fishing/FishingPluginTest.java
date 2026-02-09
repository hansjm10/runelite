/*
 * Copyright (c) 2023, Adam <Adam@sigterm.info>
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
package net.runelite.client.plugins.fishing;

import com.google.inject.Guice;
import com.google.inject.testing.fieldbinder.Bind;
import com.google.inject.testing.fieldbinder.BoundFieldModule;
import java.time.Duration;
import java.time.Instant;
import javax.inject.Inject;
import net.runelite.api.ChatMessageType;
import net.runelite.api.Client;
import net.runelite.api.Item;
import net.runelite.api.ItemContainer;
import net.runelite.api.NPC;
import net.runelite.api.Player;
import net.runelite.api.coords.WorldPoint;
import net.runelite.api.events.ChatMessage;
import net.runelite.api.events.GameTick;
import net.runelite.api.events.InteractingChanged;
import net.runelite.api.events.ItemContainerChanged;
import net.runelite.api.gameval.InventoryID;
import net.runelite.api.gameval.NpcID;
import net.runelite.client.Notifier;
import net.runelite.client.game.FishingSpot;
import net.runelite.client.ui.overlay.OverlayManager;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@RunWith(MockitoJUnitRunner.class)
public class FishingPluginTest
{
	@Inject
	private FishingPlugin fishingPlugin;

	@Mock
	@Bind
	private Client client;

	@Mock
	@Bind
	private Notifier notifier;

	@Mock
	@Bind
	private OverlayManager overlayManager;

	@Mock
	@Bind
	private FishingConfig config;

	@Mock
	@Bind
	private FishingOverlay overlay;

	@Mock
	@Bind
	private FishingSpotOverlay spotOverlay;

	@Mock
	@Bind
	private FishingSpotMinimapOverlay fishingSpotMinimapOverlay;

	@Mock
	private Player player;

	@Mock
	private ItemContainer inventory;

	@Mock
	private ItemContainer worn;

	@Before
	public void before()
	{
		Guice.createInjector(BoundFieldModule.of(this)).injectMembers(this);
		when(client.getLocalPlayer()).thenReturn(player);
		when(player.getWorldLocation()).thenReturn(new WorldPoint(0, 0, 0));
		when(client.getItemContainer(InventoryID.INV)).thenReturn(inventory);
		when(client.getItemContainer(InventoryID.WORN)).thenReturn(worn);
		when(inventory.getItems()).thenReturn(new Item[0]);
		when(worn.getItems()).thenReturn(new Item[0]);
	}

	@Test
	public void testLobster()
	{
		ChatMessage chatMessage = new ChatMessage();
		chatMessage.setType(ChatMessageType.SPAM);
		chatMessage.setMessage("You catch a Lobster.");

		fishingPlugin.onChatMessage(chatMessage);

		assertNotNull(fishingPlugin.getSession().getLastFishCaught());
	}

	@Test
	public void testAnglerfish()
	{
		ChatMessage chatMessage = new ChatMessage();
		chatMessage.setType(ChatMessageType.SPAM);
		chatMessage.setMessage("You catch an Anglerfish.");

		fishingPlugin.onChatMessage(chatMessage);

		assertNotNull(fishingPlugin.getSession().getLastFishCaught());
	}

	@Test
	public void testCormorant()
	{
		ChatMessage chatMessage = new ChatMessage();
		chatMessage.setType(ChatMessageType.SPAM);
		chatMessage.setMessage("Your cormorant returns with its catch.");

		fishingPlugin.onChatMessage(chatMessage);

		assertNotNull(fishingPlugin.getSession().getLastFishCaught());
	}

	@Test
	public void testKarambwanji()
	{
		ChatMessage chatMessage = new ChatMessage();
		chatMessage.setType(ChatMessageType.SPAM);
		chatMessage.setMessage("You catch 15 Karambwanji.");

		fishingPlugin.onChatMessage(chatMessage);

		assertNotNull(fishingPlugin.getSession().getLastFishCaught());
	}

	@Test
	public void testCurrentSpotNotClearedByItemContainerUpdateWhenActivelyFishing()
	{
		NPC npc = createFishingSpotNpc();
		setCurrentSpot(npc);
		when(player.getInteracting()).thenReturn(npc);

		fishingPlugin.onItemContainerChanged(new ItemContainerChanged(InventoryID.INV, inventory));

		assertEquals(FishingSpot.LOBSTER, fishingPlugin.getCurrentSpot());
	}

	@Test
	public void testCurrentSpotClearedByItemContainerUpdateWhenNotActivelyFishing()
	{
		setCurrentSpot(createFishingSpotNpc());
		when(player.getInteracting()).thenReturn(null);

		fishingPlugin.onItemContainerChanged(new ItemContainerChanged(InventoryID.INV, inventory));

		assertNull(fishingPlugin.getCurrentSpot());
	}

	@Test
	public void testCurrentSpotNotClearedBySessionTimeoutWhenActivelyFishing()
	{
		NPC npc = createFishingSpotNpc();
		setCurrentSpot(npc);
		when(player.getInteracting()).thenReturn(npc);
		when(config.statTimeout()).thenReturn(5);
		fishingPlugin.getSession().setLastFishCaught(Instant.now().minus(Duration.ofMinutes(10)));

		fishingPlugin.onGameTick(new GameTick());

		assertEquals(FishingSpot.LOBSTER, fishingPlugin.getCurrentSpot());
		assertNull(fishingPlugin.getSession().getLastFishCaught());
	}

	@Test
	public void testCurrentSpotClearedBySessionTimeoutWhenNotActivelyFishing()
	{
		setCurrentSpot(createFishingSpotNpc());
		when(player.getInteracting()).thenReturn(null);
		when(config.statTimeout()).thenReturn(5);
		fishingPlugin.getSession().setLastFishCaught(Instant.now().minus(Duration.ofMinutes(10)));

		fishingPlugin.onGameTick(new GameTick());

		assertNull(fishingPlugin.getCurrentSpot());
		assertNull(fishingPlugin.getSession().getLastFishCaught());
	}

	private NPC createFishingSpotNpc()
	{
		NPC npc = mock(NPC.class);
		when(npc.getId()).thenReturn(NpcID._0_40_53_RAREFISH);
		return npc;
	}

	private void setCurrentSpot(NPC npc)
	{
		fishingPlugin.onInteractingChanged(new InteractingChanged(player, npc));

		assertEquals(FishingSpot.LOBSTER, fishingPlugin.getCurrentSpot());
	}
}
