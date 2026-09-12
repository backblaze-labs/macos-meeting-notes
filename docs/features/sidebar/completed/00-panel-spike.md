# Sidebar 00 — Throwaway spike: non-activating panel in this runtime

> Status: active · Owner: Felipe Fumero · Created 2026-09-05

## Context

Every later plan assumes a borderless `NSPanel` can float above meeting apps
without stealing focus and without disturbing this app's accessory identity.
Three assumptions in that chain are **unverified against this specific codebase**:

1. `ui/macos.py` patches `applicationDidBecomeActive_` to re-hide the Dock icon
   (`hide_dock_icon_when_app_activates`, `src/meeting_memory/ui/macos.py:33`).
   A non-activating panel should never trigger it — but if the panel does
   activate the app, that hook fires on every show and may flicker the Dock.
2. `rumps` 0.4.0 owns the status item and calls
   `nsstatusitem.setMenu_(mainmenu._menu)` (`rumps/rumps.py:954`). Once a menu is
   attached, click actions are never delivered. Plan 03 depends on being able to
   detach it.
3. A floating panel is captured by screenshots, screen recordings, and screen
   shares by default. For a meeting-recording app that is probably wrong — a
   panel reading "■ Stop Recording · 12:34" sitting over your slides while you
   share your screen in the very meeting you are recording.
   `setSharingType_(NSWindowSharingNone)` is the documented opt-out, but its
   behavior against ScreenCaptureKit has shifted across macOS releases and is
   **unverified on Darwin 25.6.0**.

Confirmed already (do not re-verify): pyobjc 12.2.2 exposes every needed symbol
(`NSPanel`, `NSWindowStyleMaskNonactivatingPanel`, `NSFloatingWindowLevel`,
`NSWindowCollectionBehaviorCanJoinAllSpaces`, `NSWindowCollectionBehaviorFullScreenAuxiliary`,
`NSTrackingArea`, `NSVisualEffectView`), and the app already runs as
`NSApplicationActivationPolicyAccessory`.

**Outcome:** a scratch script, run once by hand, that answers these questions.
Nothing from this plan is committed.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Location | Scratchpad, **not** the repo | Throwaway. Committing it would trip `test_structure.py` module registration and the 300-line audit for no benefit. |
| Scope | The seven questions below, nothing more | This is a risk probe, not a prototype. No layout, no snapping, no content. |
| Blocking? | Blocks 02, 03, and the screenshot step | Plan 01 is pure math and can proceed in parallel. Question 7 decides whether `VERIFICATION.md` §3 is possible at all. |

## Out of scope

- Any layout, styling, snapping, or content — those are plans 01/02/05/06.
- Committing anything to the repository.

## Files to create

One scratch file under the session scratchpad (no repo path):

```
<scratchpad>/sidebar_spike.py    # ~80 lines, deleted after the run
```

Shape:

```python
# 1. Reproduce the app's identity
from meeting_memory.ui.macos import configure_background_app_identity
configure_background_app_identity(logging.getLogger("spike"))

# 2. Build the panel
panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
    NSMakeRect(200, 200, 240, 420),
    NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
    NSBackingStoreBuffered, False)
panel.setFloatingPanel_(True)
panel.setLevel_(NSFloatingWindowLevel)
panel.setCollectionBehavior_(CanJoinAllSpaces | FullScreenAuxiliary)
panel.setMovableByWindowBackground_(True)
panel.setOpaque_(False)
# panel.setSharingType_(NSWindowSharingNone)   # question 7 — toggle and compare
panel.orderFrontRegardless()          # NOT makeKeyAndOrderFront_

# 3. Instrument the Dock hook — log every applicationDidBecomeActive_ call
# 4. Detach the rumps menu and prove a click action is delivered
app._nsapp.nsstatusitem.setMenu_(None)
app._nsapp.nsstatusitem.button().setTarget_(handler)
app._nsapp.nsstatusitem.button().setAction_("clicked:")
```

## Questions the spike must answer

1. Does the panel appear **without** activating the app? (watch for the Dock hook firing)
2. Does it stay above a full-screen Zoom/Meet window and follow across Spaces?
3. Can you keep typing in another app while the panel is visible?
4. After `setMenu_(None)`, does a left-click on the status item deliver the action?
5. Does `button()` exist on the status item rumps 0.4.0 created? (0.4.0 predates
   the `button()`-first API but the selector should still be present on macOS 10.10+)
6. Does `setFrameAutosaveName_` round-trip the position across two runs?
7. **Does `setSharingType_(NSWindowSharingNone)` hide the panel from capture on
   this macOS version?** Test all three separately — they do not necessarily
   agree:
   - `screencapture -x /tmp/shot.png` — is the panel in the PNG?
   - QuickTime screen recording — is it in the movie?
   - A real screen share (Zoom/Meet/Slack huddle) — do others see it?

   Run each with sharing type at its default **and** set to `NSWindowSharingNone`,
   so the difference is unambiguous. The `screencapture` half is scriptable; the
   screen-share half needs a human.

## Files to modify

None.

## Verification

> This plan predates the flag and the demo harness — it deliberately references
> neither. But **keep the script**: it is the seed of
> `$SCRATCHPAD/sidebar_demo.py`, which plan 02 builds out
> ([`VERIFICATION.md`](VERIFICATION.md) §2). Screenshot convention is §3 if you
> want a record of the bare panel.

Run it by hand from the project venv with the src path set:

```bash
PYTHONPATH=src .venv/bin/python "$SCRATCHPAD/sidebar_spike.py"
```

Success is a written answer to all seven questions, recorded in this plan's
"Findings" section below before it moves to `completed/`.

## Findings

Ran `$SCRATCHPAD/sidebar_spike.py` (PYTHONPATH=src, project venv). The dock-hook
and status-item questions were verified programmatically by instrumenting
`applicationDidBecomeActive_` directly (not `hide_dock_icon`, which is also
called once directly at startup and would have produced a false positive) and
by round-tripping `setFrameAutosaveName_` across separate process
invocations. The full-screen/Spaces, keyboard-focus, and click-delivery
questions were confirmed by the owner watching a real screen and interacting
with a live run.

- [x] Panel shows without activating — `orderFrontRegardless()` on the
  `NSPanel` never fired `applicationDidBecomeActive_` in two clean runs.
- [x] Floats over full-screen meeting apps, joins all Spaces — confirmed by
  the owner: opened an app full-screen, panel stayed on top and followed
  across Spaces.
- [x] Keyboard focus stays with the other app — confirmed by the owner: typed
  into another app's field while the panel was visible, focus never moved.
  (The panel has no text field of its own by design — no layout/content is
  in scope for this plan — so there was nothing to accidentally focus.)
- [x] `setMenu_(None)` + `button().setAction_` delivers clicks — confirmed
  both structurally (no exception, no fallback path taken) and live: the
  owner clicked the "SidebarSpike" menu-bar item and the spike logged
  `STATUS ITEM CLICK DELIVERED` and quit.
- [x] `button()` present on rumps 0.4.0's status item — `True` on pyobjc
  12.2.2 / this macOS.
- [x] `setFrameAutosaveName_` persists across runs — confirmed by moving the
  panel to `(999, 555)`, calling `saveFrameUsingName_` explicitly, then
  starting a brand-new process: it restored at `(999, 555)`.
- [x] Default sharing type: panel appears in `screencapture -x` — confirmed
  automatically. See "Question 7 findings" below.
- [x] `NSWindowSharingNone`: panel hidden from `screencapture -x` — confirmed
  automatically, same section. The live screen-share leg (an actual
  Zoom/Meet/Slack participant confirming they can't see it) was **not**
  performed this round — see the decision recorded at the end of "Question 7
  findings" below.

Bugs found and fixed in the scratch script while running it (not repo code):
the original draft counted every `hide_dock_icon()` call as an activation,
which double-counts the one direct call `configure_background_app_identity`
makes at startup — fixed by wrapping `applicationDidBecomeActive_` itself.
`AppKit.NSApp` also isn't a valid attribute in this pyobjc version; use
`AppKit.NSApplication.sharedApplication()` instead.

### Question 7 findings

Added `sidebar_capture_test.py` alongside the spike: it launches
`sidebar_spike.py` with `SIDEBAR_SPIKE_CAPTURE_TEST=1` (panel renders as an
opaque, fixed-position magenta patch instead of the normal translucent dev
look, so a screenshot can be checked by pixel color) and
`SIDEBAR_SPIKE_SHARING=default` or `=none`, runs `screencapture -x -R` against
exactly that screen region, and inspects the PNG with `NSBitmapImageRep`
(no new dependency needed — AppKit is already available).

Blocked once on Screen Recording permission — `screencapture` failed with
"could not create image from display" because the process invoking it (the
Claude desktop app, which hosts this shell) didn't have that permission.
Fixed by granting it in System Settings → Privacy & Security → Screen
Recording; this is a one-time host-machine setting, not something the app
itself needs to request or handle.

Result on Darwin 25.6.0:

| Sharing type | Center-of-panel pixel (screencapture, calibrated RGB) | Panel visible? |
|---|---|---|
| default | `(0.93, 0.32, 0.97)` — magenta | **Yes** |
| `NSWindowSharingNone` | `(0.07, 0.07, 0.07)` / `(1.0, 1.0, 1.0)` (background) | **No** |

(The captured magenta isn't exact `(1, 0, 1)` because `screencapture` round-trips
through a wide-gamut color space; it's still unambiguously distinct from the
plain-background readings in the `none` case.)

**Conclusion: `setSharingType_(NSWindowSharingNone)` works on this macOS
version** for at least the `screencapture` capture path. The real-screen-share
leg (does a Zoom/Meet/Slack huddle participant see it) is still unverified —
that part is unscriptable and needs a human on an actual call.

**Decision:** proceeding to plan 01+ on the strength of the `screencapture`
result alone; the live-call confirmation is deferred rather than blocking.
`screencapture` and ScreenCaptureKit-based capture (which is what Zoom/Meet/
Slack actually use for screen share) have historically honored the same
`NSWindowSharingNone` flag, so this is a reasonably low-risk deferral, not a
blind one. Plan 02, when it actually sets this flag on the real sidebar
panel, should get one live-call confirmation before shipping — track that
there rather than re-opening this plan.

All six original questions plus question 7's `screencapture` leg are
confirmed above. Only the live-call leg of question 7 remains open, and it is
deferred to plan 02 per the decision recorded just above — not a blocker for
this plan.

**Question 7 has two downstream consequences — record both:**

- **Product.** If `NSWindowSharingNone` works, plan 02 should almost certainly
  set it, so the sidebar never leaks into a shared screen during the meeting
  being recorded. If it does *not* work, that is a real limitation worth a note
  in `docs/deferred-work.md` and a line in the feature doc, because users will
  hit it.
- **Verification.** A panel excluded from capture cannot be screenshotted, which
  makes `VERIFICATION.md` §3 impossible as written. In that case either take the
  feature-doc shots with sharing type temporarily left at default, or drop the
  screenshot step. Decide here rather than discovering it at plan 05.

## Execution order

1. Write the scratch script.
2. Run it against a real screen with a meeting app open full-screen.
3. Fill in Findings.
4. Keep the script as the starting point for plan 02's demo harness; it is never
   committed to the repository either way.

---

Once the plan is completed you need to change the directory of the plan to
`docs/features/sidebar/completed`.
