# Persistent lessons

Lessons from benchmark runs are kept as process rules, never as case content or answers.

Format: `ID | observed failure (generic) | rule change | regression test (name or NOT YET WRITTEN)`.

Seed lessons (generic):
- L1 | Large design outputs truncated in one reply | request in parts from the start | gates/tests/test_assembly.py, GP tests
- L2 | Review counted on a stale or partial file | review coverage requires whole current files | test_g2_review_of_stale_subject, test_g3_source_gate_review_stale, test_g0_partial_input
- L3 | Counting/key errors found late | run early key/count checks at Stage 3 | G3K tests in test_stage_gates.py
- L4 | External account lockouts stalled a run | wait and retry up to 3 times, then report | none

Process lessons from the head-to-head benchmark run (2026-11-10; no case content or answers):
- L5 | Gate locked on a repaired file while the reviews covered the earlier version | send the current file for re-review before the gate | test_g2_framing_repair_needs_rereview_of_current_file
- L6 | Children wrote their files but did not reply; the parent learned of it from the owner | a send is complete only on a reply ending `ANSWERED <PACKET_ID>` with a non-blank produced-files list | test_g0_file_on_disk_is_not_a_completed_send, test_g0_reply_without_answered_marker, test_g0_blank_produced_files_list
- L7 | A leftover template note went out in a sent packet | G0 rejects `TEMPLATE` text and unfilled placeholders | test_g0_template_marker_left_in_packet, test_g0_unfilled_placeholder
- L8 | Python gates were missing from the pinned workflow, so manual stand-ins were used, including for claims and certificate | publish and pin the Python gates G0-G6; no manual stand-in for an implemented gate | gates/tests/test_finish_gates.py
- L9 | The first framing left the capacity/loss rule and the decision unit implicit; a repair round closed them | the Lead Designer states both explicitly in the first framing | none (role text)

Process lessons from the second head-to-head case (2026-11-10; no case content or answers):
- L10 | A run stopped as unresolved on a field-value meaning and an entity mapping that the public schema and brief already gave | check public files before any stop; record the derivation and continue; only non-derivable items stop and go to the owner (GD, inside G0) | test_g0_stop_on_derivable_mapping_is_rejected, test_g0_derivable_item_cannot_stop_and_sources_must_be_public
- L11 | A design rule banned rates, so the descriptive group comparison was never reported | labeled descriptive rates are allowed and expected; G3 rejects a blanket ban and G5 requires the label | test_g3_blanket_rate_ban_rejected, test_g3_labeled_descriptive_rates_allowed, test_g5_rate_claim_must_be_labeled_descriptive
- L12 | The design template's placeholder fixtures (all-zero hashes) travelled with Stage 3 and only R `finalize` noticed | G0 rejects template placeholder references in packet inputs; G3 rejects them at the design lock, with a message naming the fix | test_g0_template_json_attached_as_input, test_g3_design_references_template_with_placeholder_fixtures
- L13 | Packets that failed G0 and were replaced kept blocking G6 because G0 had no supersession | mark a replaced packet `superseded_by` with reason and time; it stays sealed and is no longer counted | test_g0_superseded_packets_no_longer_block_g6, test_g0_supersession_record_must_be_complete, test_g0_superseded_packet_stays_sealed
