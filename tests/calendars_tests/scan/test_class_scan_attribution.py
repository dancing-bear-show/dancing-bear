"""Tests for child/activity attribution in scanned class-schedule emails.

Body text is taken verbatim from real provider emails (City of Richmond Hill
"Active RH" receipts and WD SWIM Richmond Inc. notices) so the parsing is
exercised against the exact phrasing those vendors emit.
"""
import unittest

from calendars.gmail_pipeline_scan_classes import GmailScanClassesProcessor
from calendars.pipeline_base import dedupe_events
from calendars.scan_common import (
    extract_activity,
    extract_child,
    is_enrollment_notice,
    is_plausible_session,
    norm_time,
    parse_clock_time,
)

CALENDAR = "Your Family"

# --- Provider A: City of Richmond Hill / "Active RH" ------------------------

ACTIVE_RH_RECEIPT = (
    "City of Richmond Hill - Online 225 East Beaver Creek Road Richmond Hill, ON "
    "L4B 3P4 Phone: (905) 771-8800 FAX: Email: recreation@richmondhill.ca Your "
    "Receipt Number is: 3290632.001 Order Summary: Blass sherwin Enrollment in "
    "Indoor Baseball (# 151046) Enrollment Effective Date :August 30, 2026 "
    "Meeting Dates: From Sep 26, 2026 to Nov 28, 2026 Each Saturday from 6:30pm "
    "to 7:30pm Except the following dates: Saturday, October 24, 2026 Saturday, "
    "October 31, 2026 Location: Oak Ridges CC - Gym A at Oak Ridges CC 12895 "
    "Bayview Avenue Richmond Hill, ON L4E 3G2 The price is $90.59."
)

# Same enrollment (# 142470) described twice: once as a pending registration
# (lowercase "enrollment in", abbreviated month) and once as a processed
# transaction (no "Order Summary:" label, full month name).
ACTIVE_RH_PENDING = (
    "Order Summary: bennet sherwin Pending enrollment in Sportball Multi-Sport "
    "(# 142470) Meeting Dates: From Apr 12, 2026 to May 31, 2026 "
    "Each Sunday from 9:30am to 10:30am Location: Elgin West"
)
ACTIVE_RH_PROCESSED = (
    "Thank you. Your transaction has been processed. bennet sherwin Enrollment in "
    "Sportball Multi-Sport (# 142470) Meeting Dates: From April 12, 2026 to "
    "May 31, 2026 Each Sunday from 9:30am to 10:30am Location: Elgin West"
)

# --- Provider B: WD SWIM Richmond Inc. --------------------------------------

WD_NEW_ENROLLMENT = (
    "Dear Vanesa Echeveste Student: Bruce Sherwin Class: Glider2-3 Sun 9:30AM "
    "Lane 5 Startdate: 09/11/2026 Dropdate: Status: wait Schedule: "
    "Sunday: 9:30am-10:00am"
)

# A transfer restates the superseded enrollment before the current one.
WD_TRANSFER = (
    "Dear Vanesa Echeveste, your student was transfered from Glider2-3 Sun "
    "2:15PM Lane 6 to Glider2-3 Sun 12:45PM Lane 2: Old Enrollment: Type: "
    "Enrollment Student: Blas Sherwin Class: Glider2-3 Sun 2:15PM Lane 6 "
    "Start Date: 09/06/2026 Drop Date: 09/06/2026 Old Time: Sunday: "
    "2:15pm-2:45pm Status: active New Enrollment: Type: Enrollment Student: "
    "Blas Sherwin Class: Glider2-3 Sun 12:45PM Lane 2 Start Date: 09/13/2026 "
    "Drop Date: New Time: Sunday: 12:45pm-1:15pm Status: active"
)

WD_MAKEUP_TOKEN = (  # nosec B105 - email body fixture, "token" here is a class makeup credit
    "Dear Vanesa Echeveste A makeup token from WD SWIM Richmond Inc. was "
    "recently created. Student: Blas Sherwin Token Type: Excused Absence Token "
    "Expiration: 09/06/2027 For: (NEW)Glider2-3 Sun 2:15PM Lane 6 on 09/06/2026"
)

# A structurally valid Active RH enrollment whose registrant reads as prose
# rather than a name, so the child key is omitted while the event still stands.
# A body with no registrant structure at all is rejected outright instead (see
# test_body_with_only_a_time_line_is_not_an_enrollment).
NO_ATTRIBUTION = (
    "Please see the enrollment in Pottery (# 9) Meeting Dates: "
    "From Sep 1, 2026 to Oct 1, 2026 Each Monday from 5:00pm to 6:00pm "
    "Location: Elgin West"
)


def extract(body: str) -> list[dict]:
    """Run the scan-classes extractor over one message body."""
    return GmailScanClassesProcessor()._extract_events(body, CALENDAR)


class ActiveRhAttributionTests(unittest.TestCase):
    """Active RH receipts carry the registrant and a real activity name."""

    def test_emits_single_event_with_child_and_activity(self):
        events = extract(ACTIVE_RH_RECEIPT)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["child"], "Blass Sherwin")
        self.assertEqual(events[0]["subject"], "Indoor Baseball")

    def test_preserves_existing_schedule_fields(self):
        event = extract(ACTIVE_RH_RECEIPT)[0]
        self.assertEqual(event["calendar"], CALENDAR)
        self.assertEqual(event["repeat"], "weekly")
        self.assertEqual(event["byday"], ["SA"])
        self.assertEqual(event["start_time"], "18:30")
        self.assertEqual(event["end_time"], "19:30")
        self.assertEqual(event["location"], "Oak Ridges")
        self.assertEqual(
            event["range"], {"start_date": "2026-09-26", "until": "2026-11-28"}
        )

    def test_pending_registration_keeps_status_word_out_of_name(self):
        event = extract(ACTIVE_RH_PENDING)[0]
        self.assertEqual(event["child"], "Bennet Sherwin")
        self.assertEqual(event["subject"], "Sportball Multi-Sport")

    def test_processed_transaction_variant_parses_without_order_summary(self):
        event = extract(ACTIVE_RH_PROCESSED)[0]
        self.assertEqual(event["child"], "Bennet Sherwin")
        self.assertEqual(event["subject"], "Sportball Multi-Sport")

    def test_pending_and_processed_pair_collapses_to_one_event(self):
        both = extract(ACTIVE_RH_PENDING) + extract(ACTIVE_RH_PROCESSED)
        self.assertEqual(len(both), 2)
        self.assertEqual(len(dedupe_events(both)), 1)

    def test_lowercase_registrant_name_is_normalized(self):
        self.assertEqual(
            extract_child("Order Summary: bruce sherwin Enrollment in Chess (# 1)"),
            "Bruce Sherwin",
        )


class ActivityNameTests(unittest.TestCase):
    """Activity names are derived from email structure, not a fixed list."""

    def test_category_variant_shape_keeps_the_hyphen(self):
        self.assertEqual(
            extract_activity("Enrollment in Chess - Intermediate (# 151046)"),
            "Chess - Intermediate",
        )

    def test_multi_word_variant(self):
        self.assertEqual(
            extract_activity("Enrollment in Culinary - Littlest Bake Shop (# 1)"),
            "Culinary - Littlest Bake Shop",
        )

    def test_activity_without_hyphen(self):
        self.assertEqual(
            extract_activity("Enrollment in Sportball Multi-Sport (# 2)"),
            "Sportball Multi-Sport",
        )

    def test_non_swim_activity_is_not_forced_to_a_known_class(self):
        self.assertEqual(
            extract_activity("Enrollment in Volleyball - Children (# 3)"),
            "Volleyball - Children",
        )

    def test_wd_swim_class_label(self):
        self.assertEqual(
            extract_activity("Class: Glider2-3 Sun 9:30AM Lane 5"), "Glider2-3"
        )

    def test_returns_none_when_no_activity_present(self):
        self.assertIsNone(
            extract_activity("Program runs Each Monday from 5:00pm to 6:00pm")
        )

    def test_handles_empty_and_none(self):
        self.assertIsNone(extract_activity(""))
        self.assertIsNone(extract_activity(None))


class WdSwimAttributionTests(unittest.TestCase):
    """WD Swim notices name the student and the class."""

    def test_new_enrollment(self):
        events = extract(WD_NEW_ENROLLMENT)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["child"], "Bruce Sherwin")
        self.assertEqual(events[0]["subject"], "Glider2-3")
        self.assertEqual(events[0]["byday"], ["SU"])
        self.assertEqual(events[0]["start_time"], "09:30")
        self.assertEqual(events[0]["end_time"], "10:00")

    def test_transfer_emits_only_the_new_slot(self):
        events = extract(WD_TRANSFER)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["start_time"], "12:45")
        self.assertEqual(events[0]["end_time"], "13:15")
        self.assertEqual(events[0]["child"], "Blas Sherwin")

    def test_transfer_does_not_emit_the_superseded_slot(self):
        times = {(ev["start_time"], ev["end_time"]) for ev in extract(WD_TRANSFER)}
        self.assertNotIn(("14:15", "14:45"), times)

    def test_transfer_does_not_emit_phantom_times_from_class_names(self):
        # "Glider2-3" previously parsed as a 2:00-3:00 time range.
        times = {(ev["start_time"], ev["end_time"]) for ev in extract(WD_TRANSFER)}
        self.assertNotIn(("02:00", "03:00"), times)

    def test_makeup_token_emits_no_recurring_event(self):
        self.assertEqual(extract(WD_MAKEUP_TOKEN), [])

    def test_student_name_stops_before_next_label(self):
        self.assertEqual(
            extract_child("Student: Bruce Sherwin Class: Glider2-3 Sun 9:30AM"),
            "Bruce Sherwin",
        )


class MissingAttributionTests(unittest.TestCase):
    """Absent registrant/activity fall back cleanly rather than emitting blanks."""

    def test_child_key_is_omitted_when_no_name_found(self):
        event = extract(NO_ATTRIBUTION)[0]
        self.assertNotIn("child", event)

    def test_subject_is_still_derived_without_a_registrant(self):
        self.assertEqual(extract(NO_ATTRIBUTION)[0]["subject"], "Pottery")

    def test_subject_falls_back_to_generic_class_without_an_activity(self):
        # WD Swim shape with a schedule but no "Class:" label to name it.
        body = (
            "Dear Vanesa Echeveste Student: Bruce Sherwin Startdate: 09/11/2026 "
            "Schedule: Monday: 5:00pm-6:00pm"
        )
        self.assertEqual(extract(body)[0]["subject"], "Class")

    def test_extract_child_returns_none_for_empty_and_none(self):
        self.assertIsNone(extract_child(""))
        self.assertIsNone(extract_child(None))

    def test_extract_child_returns_none_when_absent(self):
        self.assertIsNone(extract_child(NO_ATTRIBUTION))

    def test_body_with_only_a_time_line_is_not_an_enrollment(self):
        # No registrant anywhere: this is prose, not a registration.
        bare = "Program runs Each Monday from 5:00pm to 6:00pm Location: Elgin West"
        self.assertFalse(is_enrollment_notice(bare))
        self.assertEqual(extract(bare), [])


# ---------------------------------------------------------------------------
# Real-mail regression fixtures.
#
# Each body below is the HTML-stripped text of an actual message that produced
# a junk row before validation was added. Message ids are recorded so the
# source can be re-fetched if a provider changes its format.
# ---------------------------------------------------------------------------

# 19cdefbc6394aeaf - marketing announcement of new class slots. Four day/time
# pairs in prose, no registrant.
WD_NEW_SLOTS_ANNOUNCEMENT = (
    "Dear Parents, Due to the high demand for our Improver level lessons, we "
    "are pleased to announce that we have opened a few additional class time "
    "slots: Monday: 7:00 PM - 8:00 PM Tuesday: 4:00 PM - 5:00 PM Tuesday: "
    "5:00 PM - 6:00 PM Tuesday: 6:00 PM - 7:00 PM The reason we are able to "
    "open more Improver classes is because many swimmers have done an "
    "excellent job. Please note that spots are limited. Splashingly yours, "
    "WD Swim Richmond Hill If you'd rather not receive these messages, click "
    "here to unsubscribe."
)

# 19bd8a6293a26f05 - monthly newsletter; the camp blurb reads "9:00 AM - 12:00 PM".
WD_NEWSLETTER = (
    "Dear Vanesa , We hope you and your family enjoyed a wonderful holiday "
    "season. Let's dive into our January 2026 updates! March Break Swim Camp "
    "Announcement March 16th - 20th, 2026 (Monday to Friday) 9:00 AM - 12:00 PM "
    "5 action-packed sessions. Spaces are limited, so we encourage families to "
    "register early. Privacy Policy Reminder. Lost & Found Announcement. "
    "Best Regards, WD Swim Richmond Hill If you'd rather not receive these "
    "messages, click here to unsubscribe."
)

# 19fb4e919aeca227 - adult class announcement, "Tuesday 9:00 PM - 9:45 PM".
WD_ADULT_CLASS_ANNOUNCEMENT = (
    "Dear Vanesa , We're excited to announce that we've added a new Adult Swim "
    "Class on Tuesdays at 9:00 PM at WD Swim Richmond Hill! Class Details: "
    "Day: Tuesday Time: 9:00 PM - 9:45 PM Class Ratio: 5:1 Duration: 45 minutes "
    "Spaces are limited. Best Regards, WD Swim Richmond Hill If you'd rather "
    "not receive these messages, click here to unsubscribe."
)

# 19dc5d2d8cb77a5d - payment receipt. Names children but enrolls nobody; the
# "Glider2-3" digits previously parsed as a 02:00-03:00 range.
WD_PAYMENT_RECEIPT = (
    "WD Swim RH 563 Edward Ave Unit 12 Richmond Hill ON L4C9W7 Dear Vanesa "
    "Echeveste , A payment has been processed for your current charges, as of "
    "04/25/2026: Charge Details Sep 2026 :: Sherwin, Blas :: Glider2-3 Sun "
    "1:30PM Lane 3 $135.60 Oct 2026 :: Sherwin, Bruce :: Glider1 Sunday 1:30PM "
    "Lane 2 $135.60 Payment Details AmericanExpress ending with 1002 -- $542.40 "
    "Outstanding Balance: $0.00"
)

# 19c1b72a15e8884a - per-child skills report; dates like 02/01/2026 parsed as times.
WD_SKILLS_REPORT = (
    "From: WD SWIM Richmond Inc. Sent: Sunday, February 1, 2026 5:38:17 PM "
    "Subject: Skills Progress for Blas Check out what Blas has accomplished "
    "lately! Side Breathing Kicking on Mat/Noodle[A] 02/01/2026 Flutter Kicks "
    "in Streamline Position - 3 meters [U] 02/01/2026 Passed Glider 2.1 Glider "
    "// Glider 2.1 Sun, 02/01/2026 View Blas's Skill Tree"
)

# 19fcd2633b93aba6 - a general news digest that matched only because the scan
# query is broad. "Aug. 18" and similar prose produced 05:00-01:00.
UNRELATED_NEWSLETTER = (
    "Morning Report - Bay Area newsletter Tuesday, August 4, 2026 Battle over "
    "Livermore's protected hills. 14th Congressional District special election: "
    "The last day to register to vote in the Aug. 18 special election has "
    "passed. Fire crew hurt in six-alarm blaze: Four firefighters suffered "
    "injuries while battling flames at an apartment complex over the weekend."
)

# 19eb18f48857208c - a REAL single-session enrollment. "Meeting Dates:" carries
# one date with no "From ... to ...", and the session runs a legitimate 3 hours.
ACTIVE_RH_SINGLE_SESSION = (
    "City of Richmond Hill - Online Your Receipt Number is: 1558625.001 "
    "Order Summary: Blas Sherwin Enrollment in Adventure Series - Adventure Day "
    "(# 146425) Enrollment Effective Date :June 10, 2026 Meeting Dates: "
    "Jul 11, 2026 Saturday from 1pm to 4pm Location: Phyllis Rawlinson Park"
)

# 19e4c546bdbcfae6 - another real single session, 3h15m long.
ACTIVE_RH_TOURNAMENT = (
    "City of Richmond Hill - Online Your Receipt Number is: 1549745.001 "
    "Order Summary: Blas Sherwin Enrollment in Children's Basketball Tournament "
    "& Drills (6-8 yrs. old) (# 147623) Enrollment Effective Date :May 21, 2026 "
    "Meeting Dates: Jun 6, 2026 Saturday from 1:30pm to 4:45pm "
    "Location: Oak Ridges CC - Gym A"
)


class ImpossibleClockTimeTests(unittest.TestCase):
    """Captures outside real clock ranges are dropped, never clamped."""

    def test_hour_above_23_returns_none(self):
        self.assertIsNone(parse_clock_time("47", "00", None))
        self.assertIsNone(parse_clock_time("80", "00", None))

    def test_minute_above_59_returns_none(self):
        self.assertIsNone(parse_clock_time("10", "98", None))

    def test_valid_times_still_parse(self):
        self.assertEqual(parse_clock_time("9", "30", "am"), "09:30")
        self.assertEqual(parse_clock_time("1", "30", "pm"), "13:30")
        self.assertEqual(parse_clock_time("12", "00", "am"), "00:00")

    def test_norm_time_is_unchanged_for_existing_callers(self):
        # The Outlook path still uses norm_time and expects a plain string.
        self.assertEqual(norm_time("14", "30", None), "14:30")

    def test_skills_report_emits_nothing(self):
        self.assertEqual(extract(WD_SKILLS_REPORT), [])

    def test_unrelated_newsletter_emits_nothing(self):
        self.assertEqual(extract(UNRELATED_NEWSLETTER), [])


class SessionDurationTests(unittest.TestCase):
    """Implausible or inverted durations are rejected."""

    def test_rejects_end_before_start(self):
        self.assertFalse(is_plausible_session("17:00", "13:00"))

    def test_rejects_zero_length(self):
        self.assertFalse(is_plausible_session("10:00", "10:00"))

    def test_rejects_five_hour_span(self):
        self.assertFalse(is_plausible_session("15:00", "20:00"))

    def test_rejects_thirteen_hour_span(self):
        self.assertFalse(is_plausible_session("05:30", "18:15"))

    def test_accepts_typical_class(self):
        self.assertTrue(is_plausible_session("09:30", "10:30"))

    def test_accepts_real_three_hour_session(self):
        # "Adventure Series - Adventure Day" genuinely runs 13:00-16:00.
        self.assertTrue(is_plausible_session("13:00", "16:00"))

    def test_accepts_real_three_hour_fifteen_session(self):
        self.assertTrue(is_plausible_session("13:30", "16:45"))

    def test_rejects_malformed_input(self):
        self.assertFalse(is_plausible_session("", "10:00"))
        self.assertFalse(is_plausible_session("notatime", "10:00"))


class ProseNameRejectionTests(unittest.TestCase):
    """Marketing prose must not be mistaken for a registrant name."""

    def test_rejects_have_found(self):
        self.assertIsNone(
            extract_child("Many families have found enrollment in our programs")
        )

    def test_rejects_sign_up_and(self):
        self.assertIsNone(
            extract_child("Complete the sign-up and enrollment in minutes")
        )

    def test_rejects_the_highest(self):
        self.assertIsNone(
            extract_child("We offer the highest enrollment in the region")
        )

    def test_still_accepts_lowercase_real_name(self):
        # Real names arrive lowercase, so a capitalization test would be wrong.
        self.assertEqual(
            extract_child("Order Summary: bennet sherwin Pending enrollment in X (# 1)"),
            "Bennet Sherwin",
        )

    def test_still_accepts_vendor_typo_name(self):
        self.assertEqual(
            extract_child("Order Summary: Blass sherwin Enrollment in Baseball (# 1)"),
            "Blass Sherwin",
        )

    def test_still_accepts_name_after_sentence_boundary(self):
        self.assertEqual(
            extract_child(
                "Your transaction has been processed. bennet sherwin Enrollment in X (# 1)"
            ),
            "Bennet Sherwin",
        )


class NonEnrollmentEmailTests(unittest.TestCase):
    """Broadcasts and reports carry day/time text but enroll nobody."""

    def test_new_slots_announcement_emits_nothing(self):
        self.assertEqual(extract(WD_NEW_SLOTS_ANNOUNCEMENT), [])

    def test_newsletter_emits_nothing(self):
        self.assertEqual(extract(WD_NEWSLETTER), [])

    def test_adult_class_announcement_emits_nothing(self):
        self.assertEqual(extract(WD_ADULT_CLASS_ANNOUNCEMENT), [])

    def test_payment_receipt_emits_nothing(self):
        self.assertEqual(extract(WD_PAYMENT_RECEIPT), [])

    def test_payment_receipt_does_not_emit_phantom_time(self):
        # "Glider2-3" previously yielded a 02:00-03:00 "Private Lessons" row.
        times = {(ev["start_time"], ev["end_time"]) for ev in extract(WD_PAYMENT_RECEIPT)}
        self.assertNotIn(("02:00", "03:00"), times)

    def test_enrollment_notice_accepts_both_providers(self):
        self.assertTrue(is_enrollment_notice(ACTIVE_RH_RECEIPT))
        self.assertTrue(is_enrollment_notice(WD_NEW_ENROLLMENT))
        self.assertTrue(is_enrollment_notice(WD_TRANSFER))

    def test_enrollment_notice_rejects_broadcasts(self):
        self.assertFalse(is_enrollment_notice(WD_NEWSLETTER))
        self.assertFalse(is_enrollment_notice(WD_NEW_SLOTS_ANNOUNCEMENT))
        self.assertFalse(is_enrollment_notice(WD_PAYMENT_RECEIPT))
        self.assertFalse(is_enrollment_notice(UNRELATED_NEWSLETTER))

    def test_enrollment_notice_handles_empty(self):
        self.assertFalse(is_enrollment_notice(""))
        self.assertFalse(is_enrollment_notice(None))


class SingleSessionEnrollmentTests(unittest.TestCase):
    """One-off sessions have no date range but are still real enrollments."""

    def test_single_session_survives(self):
        events = extract(ACTIVE_RH_SINGLE_SESSION)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["child"], "Blas Sherwin")
        self.assertEqual(events[0]["subject"], "Adventure Series - Adventure Day")
        self.assertEqual(events[0]["start_time"], "13:00")
        self.assertEqual(events[0]["end_time"], "16:00")

    def test_tournament_survives(self):
        events = extract(ACTIVE_RH_TOURNAMENT)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["child"], "Blas Sherwin")
        self.assertEqual(
            events[0]["subject"], "Children's Basketball Tournament & Drills"
        )
        self.assertEqual(events[0]["start_time"], "13:30")
        self.assertEqual(events[0]["end_time"], "16:45")

    def test_meeting_dates_without_from_is_an_enrollment(self):
        self.assertTrue(is_enrollment_notice(ACTIVE_RH_SINGLE_SESSION))
        self.assertTrue(is_enrollment_notice(ACTIVE_RH_TOURNAMENT))

if __name__ == "__main__":
    unittest.main()
