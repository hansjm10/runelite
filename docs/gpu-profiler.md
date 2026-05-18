# GPU Profiler

RuneLite's GPU profiler is a developer tool for the GPU plugin. It is disabled by default. Enable it in the GPU plugin configuration with **GPU profiler**.

The profiler records CPU timings for renderer work and, when the driver supports OpenGL timer queries, GPU elapsed time for major GL command ranges. CPU timings measure how long the client spent preparing and submitting work. GPU timings measure elapsed execution time for commands between `GL_TIME_ELAPSED` query begin/end calls; they are not wall-clock frame latency.

The overlay separates CPU, GPU, and swap/present timing:

- CPU frame and phase timings include Java work, driver call overhead, and stalls visible to the client thread.
- GPU timings are delayed because query results are read asynchronously several frames later only after `GL_QUERY_RESULT_AVAILABLE` reports completion.
- `swapBuffers` time is CPU wait time and can include vsync, compositor behavior, driver queue throttling, or present blocking. It should not be added to GPU render time.

IntelliJ profiling, JFR, and async-profiler are still useful for Java-side allocation and CPU diagnosis, but they cannot directly measure GPU command execution, shader cost, MSAA resolve cost, GPU-side texture upload effects, or driver present behavior.

When profiling is enabled, the plugin preallocates a bounded ring of timer queries and a bounded sample history. It does not call `glFinish` and does not block on timer query results in the normal frame path. Recent GPU timings may show as unavailable until the query ring is polled.

The overlay right-click menu provides:

- **Reset** to clear the rolling sample history.
- **Export CSV** to write bounded samples to `.runelite/gpu-profiler/`.

Debug markers and object labels are emitted only when profiling and profiler debug markers are enabled and the driver supports `GL_KHR_debug`. These labels are intended for RenderDoc, Nsight Graphics, Intel GPA, apitrace, and similar capture tools. Platform support varies by driver, OpenGL profile, operating system, and capture tool.

Known limitations:

- GPU phase time is elapsed command time inside query scopes, not total end-to-end frame latency.
- Dynamic and temporary model upload costs can appear across both CPU upload phases and later GPU draw phases.
- Texture and buffer uploads may show CPU cost immediately while GPU-visible cost appears in later scoped GPU work.
- Vsync, unlocked FPS, adaptive sync, and OS compositor behavior can dominate `swapBuffers` without increasing measured GPU render time.
- Unsupported or unreliable timer queries degrade to CPU-only data; unavailable GPU values are exported blank and shown as `n/a`.
