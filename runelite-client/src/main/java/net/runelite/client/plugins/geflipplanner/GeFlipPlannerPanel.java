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

import java.awt.BorderLayout;
import java.awt.Font;
import java.io.IOException;
import java.nio.file.NoSuchFileException;
import java.time.Clock;
import java.util.concurrent.CancellationException;
import java.util.concurrent.ExecutionException;
import javax.swing.BorderFactory;
import javax.swing.BoxLayout;
import javax.swing.JButton;
import javax.swing.JPanel;
import javax.swing.JTextArea;
import javax.swing.SwingUtilities;
import javax.swing.SwingWorker;
import javax.swing.Timer;
import net.runelite.client.ui.ColorScheme;
import net.runelite.client.ui.PluginPanel;

class GeFlipPlannerPanel extends PluginPanel
{
	@FunctionalInterface
	interface PlanSource
	{
		FlipPlan load() throws IOException;
	}

	private final Clock clock;
	private final PlanSource source;
	private final JButton refresh = new JButton("Load / Refresh");
	private final JTextArea status = textArea();
	private final JTextArea details = textArea();
	private final Timer expiryTimer;
	private SwingWorker<FlipPlan, Void> worker;
	private FlipPlan displayedPlan;
	private long generation;
	private boolean closed;

	GeFlipPlannerPanel(Clock clock, PlanSource source)
	{
		this.clock = clock;
		this.source = source;
		setLayout(new BorderLayout(0, 10));
		setBorder(BorderFactory.createEmptyBorder(10, 10, 10, 10));
		JPanel content = new JPanel();
		content.setLayout(new BoxLayout(content, BoxLayout.Y_AXIS));
		content.setBackground(ColorScheme.DARK_GRAY_COLOR);
		JTextArea notice = textArea();
		notice.setText("MAIN-GAME-ONLY RESEARCH\nACCOUNT LIMITS UNVERIFIED\n"
			+ "Check your actual cash, free GE slots and buy limits yourself. No account data is read.\n\n"
			+ "Conditional quoted margins only, NOT expected or realized profit. No fill probabilities are known.\n\n"
			+ "Manual local file: .runelite/ge-flip-planner/plan.json\n\n");
		status.setFont(status.getFont().deriveFont(Font.BOLD));
		status.setForeground(ColorScheme.BRAND_ORANGE);
		status.setText("No plan loaded. Click Load / Refresh.\n\n");
		content.add(notice);
		content.add(status);
		content.add(details);
		add(refresh, BorderLayout.NORTH);
		add(content, BorderLayout.CENTER);
		refresh.addActionListener(event -> loadPlan());
		// Only expire the in-memory display. This timer never reads or reloads a file.
		expiryTimer = new Timer(1000, event -> expireSnapshot());
	}

	private static JTextArea textArea()
	{
		JTextArea text = new JTextArea();
		text.setEditable(false);
		text.setLineWrap(true);
		text.setWrapStyleWord(true);
		text.setOpaque(false);
		return text;
	}

	void loadPlan()
	{
		assert SwingUtilities.isEventDispatchThread();
		if (closed)
		{
			return;
		}
		long request = ++generation;
		if (worker != null)
		{
			worker.cancel(true);
		}
		clearPlan("Loading local plan...\n\n");
		worker = new SwingWorker<FlipPlan, Void>()
		{
			@Override
			protected FlipPlan doInBackground() throws IOException
			{
				return source.load();
			}

			@Override
			protected void done()
			{
				// Cancellation alone is insufficient: old completions may already be queued.
				if (closed || request != generation)
				{
					return;
				}
				worker = null;
				try
				{
					showPlan(get());
				}
				catch (CancellationException ex)
				{
					clearPlan("Loading cancelled. No candidates displayed.\n\n");
				}
				catch (InterruptedException ex)
				{
					Thread.currentThread().interrupt();
					clearPlan("Loading interrupted. No candidates displayed.\n\n");
				}
				catch (ExecutionException ex)
				{
					clearPlan(ex.getCause() instanceof NoSuchFileException
						? "No local plan file found. No candidates displayed.\n\n"
						: "Invalid or unreadable local plan. No candidates displayed.\n\n");
				}
			}
		};
		worker.execute();
	}

	private void showPlan(FlipPlan plan)
	{
		if (plan.isExpired(clock.instant()))
		{
			clearPlan("STALE SNAPSHOT / NOT CURRENT\nCandidate details hidden. Load a newly generated plan.\n\n");
			return;
		}
		displayedPlan = plan;
		StringBuilder text = new StringBuilder()
			.append("Generated: ").append(plan.getGeneratedAt())
			.append("\nAs of: ").append(plan.getAsOf());
		if (!plan.isHistorical())
		{
			text.append("\nExpires: ").append(plan.getExpiresAt());
			expiryTimer.start();
		}
		text.append("\nPolicy: ").append(plan.getPolicy())
			.append("\nAssumed bankroll: ").append(plan.getBankrollGp()).append(" GP")
			.append("\nCash reserve: ").append(plan.getCashReserveGp()).append(" GP")
			.append("\nAssumed slots: ").append(plan.getAvailableSlots())
			.append("\nSession: ").append(plan.getSessionMinutes()).append(" minutes\n\n");
		for (String warning : plan.getWarnings())
		{
			text.append("Warning: ").append(warning).append("\n\n");
		}
		if (plan.getCandidates().isEmpty())
		{
			text.append("NO TRADE: No candidates in this plan.\n");
		}
		for (FlipPlan.Candidate candidate : plan.getCandidates())
		{
			text.append(candidate.getName()).append(" (item ").append(candidate.getItemId()).append(")\n")
				.append("Quoted buy: ").append(candidate.getBuyPrice()).append(" GP\n")
				.append("Quoted sell: ").append(candidate.getSellPrice()).append(" GP\n")
				.append("Quantity: ").append(candidate.getQuantity()).append("\n")
				.append("Capital: ").append(candidate.getCapitalGp()).append(" GP\n")
				.append("Quoted tax per item: ").append(candidate.getTaxPerItemGp()).append(" GP\n")
				.append("Conditional quoted margin per item: ").append(candidate.getNetMarginPerItemGp()).append(" GP\n\n");
		}
		// JTextArea always renders literal text, including file-provided HTML-like strings.
		details.setText(text.toString());
		details.setCaretPosition(0);
		status.setText(plan.isHistorical()
			? "HISTORICAL / NOT CURRENT\nNON-ACTIONABLE: historical research only.\n\n"
			: "EXPERIMENTAL / UNVALIDATED FILLS\nResearch only; not live trade advice.\n\n");
		revalidate();
	}

	void expireSnapshot()
	{
		assert SwingUtilities.isEventDispatchThread();
		if (displayedPlan != null && displayedPlan.isExpired(clock.instant()))
		{
			clearPlan("STALE SNAPSHOT / NOT CURRENT\nCandidate details hidden. Load a newly generated plan.\n\n");
		}
	}

	private void clearPlan(String message)
	{
		expiryTimer.stop();
		displayedPlan = null;
		details.setText("");
		status.setText(message);
		revalidate();
		repaint();
	}

	void close()
	{
		assert SwingUtilities.isEventDispatchThread();
		closed = true;
		++generation;
		if (worker != null)
		{
			worker.cancel(true);
			worker = null;
		}
		clearPlan("Planner disabled.\n\n");
		refresh.setEnabled(false);
	}
}
