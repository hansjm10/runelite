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
import com.google.gson.JsonObject;
import java.awt.Component;
import java.awt.Container;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import javax.swing.JButton;
import javax.swing.JTextArea;
import javax.swing.SwingUtilities;
import javax.swing.event.DocumentEvent;
import javax.swing.event.DocumentListener;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.CLOCK;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.NOW;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.bytes;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.candidate;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.historical;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.parse;
import static net.runelite.client.plugins.geflipplanner.PlanTestData.snapshot;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.After;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

public class GeFlipPlannerPanelTest
{
	@Rule
	public TemporaryFolder temporary = new TemporaryFolder();

	private GeFlipPlannerPanel panel;

	@After
	public void tearDown() throws Exception
	{
		if (panel != null)
		{
			SwingUtilities.invokeAndWait(panel::close);
		}
	}

	@Test
	public void manualLoadRunsOffEdtAndShowsResearchWarnings() throws Exception
	{
		AtomicInteger loads = new AtomicInteger();
		AtomicBoolean loadedOnEdt = new AtomicBoolean();
		create(CLOCK, () ->
		{
			loads.incrementAndGet();
			loadedOnEdt.set(SwingUtilities.isEventDispatchThread());
			return parse(snapshot());
		});
		assertEquals(0, loads.get());
		assertTrue(text().contains("No plan loaded"));
		awaitText("EXPERIMENTAL / UNVALIDATED FILLS", this::clickRefresh);
		assertEquals(1, loads.get());
		assertFalse(loadedOnEdt.get());
		assertTrue(text().contains("MAIN-GAME-ONLY RESEARCH"));
		assertTrue(text().contains("ACCOUNT LIMITS UNVERIFIED"));
		assertTrue(text().contains("NOT expected or realized profit"));
		assertTrue(text().contains("Example item"));
	}

	@Test
	public void historicalIsProminentlyNonActionableAndNeverExpires() throws Exception
	{
		MutableClock clock = new MutableClock();
		create(clock, () -> parse(historical()));
		awaitText("HISTORICAL / NOT CURRENT", this::clickRefresh);
		assertTrue(text().contains("NON-ACTIONABLE"));
		assertTrue(text().contains("Example item"));
		clock.now = NOW.plusSeconds(1000000);
		SwingUtilities.invokeAndWait(panel::expireSnapshot);
		assertTrue(text().contains("Example item"));
	}

	@Test
	public void emptyPlanDisplaysNoTradeState() throws Exception
	{
		JsonObject plan = snapshot();
		plan.add("candidates", new JsonArray());
		create(CLOCK, () -> parse(plan));
		awaitText("NO TRADE", this::clickRefresh);
		assertFalse(text().contains("Quoted buy:"));
	}

	@Test
	public void htmlIsDisplayedAsLiteralText() throws Exception
	{
		JsonObject plan = snapshot();
		String literal = "<html><img src='https://invalid.example/image'>";
		candidate(plan).addProperty("name", literal);
		plan.getAsJsonArray("warnings").add("<html><b>Warning</b>");
		create(CLOCK, () -> parse(plan));
		awaitText("EXPERIMENTAL", this::clickRefresh);
		assertTrue(text().contains(literal));
		assertTrue(text().contains("<html><b>Warning</b>"));
		SwingUtilities.invokeAndWait(() ->
		{
			for (JTextArea area : textAreas(panel))
			{
				assertFalse(area.isEditable());
			}
		});
	}

	@Test
	public void missingFileClearsPreviousCandidates() throws Exception
	{
		Path path = loadedFile();
		Files.delete(path);
		awaitText("No local plan file found", () ->
		{
			clickRefresh();
			assertFalse(textOnEdt().contains("Example item"));
		});
		assertFalse(text().contains("Example item"));
	}

	@Test
	public void corruptFileClearsPreviousCandidates() throws Exception
	{
		Path path = loadedFile();
		Files.write(path, new byte[]{'{'});
		awaitText("Invalid or unreadable", this::clickRefresh);
		assertFalse(text().contains("Example item"));
	}

	@Test
	public void oversizedFileClearsPreviousCandidates() throws Exception
	{
		Path path = loadedFile();
		Files.write(path, new byte[FlipPlanParser.MAX_BYTES + 1]);
		awaitText("Invalid or unreadable", this::clickRefresh);
		assertFalse(text().contains("Example item"));
	}

	@Test
	public void futureFileClearsPreviousCandidates() throws Exception
	{
		Path path = loadedFile();
		JsonObject future = snapshot();
		future.addProperty("generatedAt", NOW.plusSeconds(61).toString());
		Files.write(path, bytes(future));
		awaitText("Invalid or unreadable", this::clickRefresh);
		assertFalse(text().contains("Example item"));
	}

	@Test
	public void staleRefreshHidesPriorAndIncomingCandidates() throws Exception
	{
		Path path = loadedFile();
		JsonObject stale = snapshot();
		stale.addProperty("generatedAt", NOW.minusSeconds(300).toString());
		stale.addProperty("asOf", NOW.minusSeconds(360).toString());
		stale.addProperty("expiresAt", NOW.toString());
		Files.write(path, bytes(stale));
		awaitText("STALE SNAPSHOT / NOT CURRENT", this::clickRefresh);
		assertFalse(text().contains("Example item"));
		assertFalse(text().contains("Quoted buy:"));
	}

	@Test
	public void expiryHidesCandidatesWithoutAnyFileReload() throws Exception
	{
		MutableClock clock = new MutableClock();
		AtomicInteger loads = new AtomicInteger();
		create(clock, () ->
		{
			loads.incrementAndGet();
			return parse(snapshot());
		});
		awaitText("EXPERIMENTAL", this::clickRefresh);
		clock.now = NOW.plusSeconds(300);
		SwingUtilities.invokeAndWait(panel::expireSnapshot);
		assertTrue(text().contains("STALE SNAPSHOT"));
		assertFalse(text().contains("Example item"));
		assertEquals(1, loads.get());
	}

	@Test
	public void actualSwingTimerExpiresWithoutReloading() throws Exception
	{
		MutableClock clock = new MutableClock();
		AtomicInteger loads = new AtomicInteger();
		create(clock, () ->
		{
			loads.incrementAndGet();
			return parse(snapshot());
		});
		awaitText("EXPERIMENTAL", this::clickRefresh);
		awaitText("STALE SNAPSHOT", () -> clock.now = NOW.plusSeconds(300));
		assertFalse(text().contains("Example item"));
		assertEquals(1, loads.get());
	}

	@Test
	public void delayedLoadIsCheckedForExpiryAtDisplayTime() throws Exception
	{
		MutableClock clock = new MutableClock();
		create(clock, () ->
		{
			FlipPlan plan = parse(snapshot());
			clock.now = NOW.plusSeconds(300);
			return plan;
		});
		awaitText("STALE SNAPSHOT", this::clickRefresh);
		assertFalse(text().contains("Example item"));
	}

	@Test
	public void oldLoadCannotOverwriteNewerResult() throws Exception
	{
		CountDownLatch started = new CountDownLatch(1);
		CountDownLatch release = new CountDownLatch(1);
		CountDownLatch finished = new CountDownLatch(1);
		AtomicInteger loads = new AtomicInteger();
		create(CLOCK, () ->
		{
			if (loads.incrementAndGet() == 1)
			{
				started.countDown();
				awaitIgnoringInterrupt(release);
				finished.countDown();
				return parse(historical());
			}
			return parse(snapshot());
		});
		try
		{
			SwingUtilities.invokeAndWait(this::clickRefresh);
			assertTrue(started.await(10, TimeUnit.SECONDS));
			awaitText("EXPERIMENTAL", this::clickRefresh);
		}
		finally
		{
			release.countDown();
		}
		assertTrue(finished.await(10, TimeUnit.SECONDS));
		assertTrue(text().contains("EXPERIMENTAL"));
		assertFalse(text().contains("HISTORICAL"));
	}

	@Test
	public void shutdownRejectsLateLoadAndFurtherRefresh() throws Exception
	{
		CountDownLatch started = new CountDownLatch(1);
		CountDownLatch release = new CountDownLatch(1);
		CountDownLatch finished = new CountDownLatch(1);
		AtomicInteger loads = new AtomicInteger();
		create(CLOCK, () ->
		{
			loads.incrementAndGet();
			started.countDown();
			awaitIgnoringInterrupt(release);
			finished.countDown();
			return parse(snapshot());
		});
		try
		{
			SwingUtilities.invokeAndWait(this::clickRefresh);
			assertTrue(started.await(10, TimeUnit.SECONDS));
			SwingUtilities.invokeAndWait(panel::close);
		}
		finally
		{
			release.countDown();
		}
		assertTrue(finished.await(10, TimeUnit.SECONDS));
		SwingUtilities.invokeAndWait(panel::loadPlan);
		assertTrue(text().contains("Planner disabled"));
		assertFalse(text().contains("Example item"));
		assertEquals(1, loads.get());
	}

	private Path loadedFile() throws Exception
	{
		Path path = temporary.newFile("plan.json").toPath();
		Files.write(path, bytes(snapshot()));
		create(CLOCK, () -> FlipPlanLoader.load(path, CLOCK));
		awaitText("EXPERIMENTAL", this::clickRefresh);
		assertTrue(text().contains("Example item"));
		return path;
	}

	private void create(Clock clock, GeFlipPlannerPanel.PlanSource source) throws Exception
	{
		SwingUtilities.invokeAndWait(() -> panel = new GeFlipPlannerPanel(clock, source));
	}

	private void clickRefresh()
	{
		for (Component component : panel.getComponents())
		{
			if (component instanceof JButton)
			{
				((JButton) component).doClick(0);
				return;
			}
		}
		throw new AssertionError("Refresh button missing");
	}

	private String text() throws Exception
	{
		String[] value = new String[1];
		SwingUtilities.invokeAndWait(() -> value[0] = textOnEdt());
		return value[0];
	}

	private String textOnEdt()
	{
		StringBuilder result = new StringBuilder();
		for (JTextArea area : textAreas(panel))
		{
			result.append(area.getText());
		}
		return result.toString();
	}

	private static List<JTextArea> textAreas(Container container)
	{
		List<JTextArea> result = new ArrayList<>();
		for (Component component : container.getComponents())
		{
			if (component instanceof JTextArea)
			{
				result.add((JTextArea) component);
			}
			else if (component instanceof Container)
			{
				result.addAll(textAreas((Container) component));
			}
		}
		return result;
	}

	private void awaitText(String expected, Runnable action) throws Exception
	{
		CountDownLatch shown = new CountDownLatch(1);
		DocumentListener listener = new DocumentListener()
		{
			@Override
			public void insertUpdate(DocumentEvent event)
			{
				if (textOnEdt().contains(expected))
				{
					shown.countDown();
				}
			}

			@Override
			public void removeUpdate(DocumentEvent event)
			{
			}

			@Override
			public void changedUpdate(DocumentEvent event)
			{
			}
		};
		SwingUtilities.invokeAndWait(() ->
		{
			textAreas(panel).forEach(area -> area.getDocument().addDocumentListener(listener));
			action.run();
		});
		try
		{
			assertTrue("Waiting for " + expected, shown.await(10, TimeUnit.SECONDS));
		}
		finally
		{
			SwingUtilities.invokeAndWait(() -> textAreas(panel).forEach(area -> area.getDocument().removeDocumentListener(listener)));
		}
	}

	private static void awaitIgnoringInterrupt(CountDownLatch latch) throws IOException
	{
		for (;;)
		{
			try
			{
				if (!latch.await(10, TimeUnit.SECONDS))
				{
					throw new IOException("Test load gate timed out");
				}
				return;
			}
			catch (InterruptedException ignored)
			{
				// Simulate an IO operation that completes despite cancellation.
			}
		}
	}

	private static class MutableClock extends Clock
	{
		private volatile Instant now = NOW;

		@Override
		public ZoneId getZone()
		{
			return ZoneOffset.UTC;
		}

		@Override
		public Clock withZone(ZoneId zone)
		{
			return this;
		}

		@Override
		public Instant instant()
		{
			return now;
		}
	}
}
