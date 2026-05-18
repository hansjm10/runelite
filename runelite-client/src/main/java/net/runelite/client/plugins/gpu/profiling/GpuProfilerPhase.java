/*
 * Copyright (c) 2026, Adam <Adam@sigterm.info>
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
package net.runelite.client.plugins.gpu.profiling;

public enum GpuProfilerPhase
{
	FRAME("Frame", "frame", false),
	SCENE_SETUP("Scene setup", "scene_setup", true),
	OPAQUE_ZONES("Opaque zones", "opaque_zones", true),
	ALPHA_ZONES("Alpha zones", "alpha_zones", true),
	DYNAMIC_MODELS("Dynamic models", "dynamic_models", true),
	TEMP_MODELS("Temp models", "temp_models", false),
	ZONE_REBUILD("Zone rebuild", "zone_rebuild", false),
	TEXTURE_UPLOAD("Texture upload", "texture_upload", true),
	SCENE_FBO_BLIT("Scene FBO blit", "scene_fbo_blit", true),
	INTERFACE_TEXTURE("Interface texture", "interface_texture", true),
	UI_DRAW("UI draw", "ui_draw", true),
	SWAP_BUFFERS("Swap buffers", "swap_buffers", false),
	DRAW_COMPLETE("Draw complete", "draw_complete", false);

	public static final GpuProfilerPhase[] VALUES = values();

	private final String displayName;
	private final String csvName;
	private final boolean gpuTimed;

	GpuProfilerPhase(String displayName, String csvName, boolean gpuTimed)
	{
		this.displayName = displayName;
		this.csvName = csvName;
		this.gpuTimed = gpuTimed;
	}

	public String getDisplayName()
	{
		return displayName;
	}

	public String getCsvName()
	{
		return csvName;
	}

	public boolean isGpuTimed()
	{
		return gpuTimed;
	}
}
