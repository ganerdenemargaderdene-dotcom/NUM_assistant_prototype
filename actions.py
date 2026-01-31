from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Text, Tuple

import re
import sqlite3
import yaml

from rasa_sdk import Action, FormValidationAction, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, EventType
from rasa_sdk.types import DomainDict

# -----------------------------
# Tuition helpers
# -----------------------------

DB_PATH = Path(__file__).resolve().parent / "tuition.db"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tuition_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            admission_group TEXT,
            faculty TEXT,
            general_credits REAL,
            major_credits REAL,
            general_rate REAL,
            major_rate REAL,
            total_tuition REAL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """
    )


def ensure_user(conn: sqlite3.Connection, sender_id: str) -> int:
    now = utc_now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO users(sender_id, created_at) VALUES(?, ?)",
        (sender_id, now),
    )
    row = conn.execute(
        "SELECT id FROM users WHERE sender_id = ?",
        (sender_id,),
    ).fetchone()
    return int(row[0])


def _load_pricing() -> Dict[str, Any]:
    pricing_path = Path(__file__).resolve().parent / "pricing.yml"
    with pricing_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip().replace(",", ".")
        return float(s)
    except Exception:
        return None


def is_english(tracker: Tracker) -> bool:
    lang = (tracker.get_slot("language") or "").strip().lower()
    return lang in {"english", "en", "eng"}


def detect_language_from_text(text: str) -> Optional[str]:
    t = (text or "").strip()
    if not t:
        return None

    # If Mongolian Cyrillic is present, treat as Mongolian.
    if any("\u0400" <= ch <= "\u04FF" for ch in t):
        return "mongolian"

    # Heuristic: English keywords in Latin script.
    english_keywords = {
        "hello", "hi", "hey", "english", "calculate", "gpa", "tuition", "location",
        "locations", "leave", "absence", "grade", "request", "bye", "goodbye",
        "dorm", "dormitory", "academic", "building", "course", "credit", "score",
    }
    lowered = t.lower()
    if any(word in lowered for word in english_keywords):
        return "english"

    return None


class ActionAutoSetLanguage(Action):
    def name(self) -> str:
        return "action_auto_set_language"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[EventType]:
        text = tracker.latest_message.get("text") or ""
        lang = detect_language_from_text(text)
        if lang:
            return [SlotSet("language", lang)]
        return []


class ValidateTuitionForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_tuition_form"

    def validate_admission_group(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        intent = tracker.latest_message.get("intent", {}).get("name")

        intent_to_group = {
            "choose_admission_before_2024_2025": "before_2024_2025",
            "choose_admission_2024_2025": "2024_2025",
            "choose_admission_2025_2026": "2025_2026",
        }

        if intent in intent_to_group:
            return {"admission_group": intent_to_group[intent]}

        allowed = {"before_2024_2025", "2024_2025", "2025_2026"}
        if slot_value in allowed:
            return {"admission_group": slot_value}

        if is_english(tracker):
            dispatcher.utter_message(text="Please select an option using the buttons.")
        else:
            dispatcher.utter_message(text="Сонголтоо товч дээр дарж сонгоорой.")
        return {"admission_group": None}

    def validate_faculty(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        pricing = _load_pricing()
        group = tracker.get_slot("admission_group")
        if not group or group not in pricing:
            if is_english(tracker):
                dispatcher.utter_message(text="Please select the admission year first.")
            else:
                dispatcher.utter_message(text="Эхлээд элсэлтийн оноо сонгоорой.")
            return {"faculty": None}

        faculties = set(pricing[group].keys())
        if slot_value in faculties:
            return {"faculty": slot_value}

        if is_english(tracker):
            dispatcher.utter_message(text="Please select your school/faculty using the buttons.")
        else:
            dispatcher.utter_message(text="Бүрэлдэхүүн/салбараа товч дээр дарж сонгоорой.")
        return {"faculty": None}

    def validate_general_credits(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        v = _to_float(slot_value)
        if v is None or v < 0:
            if is_english(tracker):
                dispatcher.utter_message(text="Enter a number greater than or equal to 0 for general-education credits.")
            else:
                dispatcher.utter_message(text="Ерөнхий суурь кредитийг 0-ээс их эсвэл тэнцүү тоогоор оруулна уу.")
            return {"general_credits": None}
        return {"general_credits": v}

    def validate_major_credits(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[Text, Any]:
        v = _to_float(slot_value)
        if v is None or v < 0:
            if is_english(tracker):
                dispatcher.utter_message(text="Enter a number greater than or equal to 0 for major/specialization credits.")
            else:
                dispatcher.utter_message(text="Мэргэжлийн суурь/мэргэших кредитийг 0-ээс их эсвэл тэнцүү тоогоор оруулна уу.")
            return {"major_credits": None}
        return {"major_credits": v}


class ActionCalculateTuition(Action):
    def name(self) -> Text:
        return "action_calculate_tuition"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        pricing = _load_pricing()

        group = tracker.get_slot("admission_group")
        faculty = tracker.get_slot("faculty")
        gen_cr = _to_float(tracker.get_slot("general_credits")) or 0.0
        maj_cr = _to_float(tracker.get_slot("major_credits")) or 0.0

        if not group or not faculty:
            if is_english(tracker):
                dispatcher.utter_message(text="Missing information. Please start again with 'calculate tuition'.")
            else:
                dispatcher.utter_message(text="Мэдээлэл дутуу байна. Дахиад 'төлбөр бодоорой' гэж эхлүүлнэ үү.")
            return []

        try:
            rates = pricing[group][faculty]
            gen_rate = float(rates["general"])
            maj_rate = float(rates["major"])
        except Exception:
            if is_english(tracker):
                dispatcher.utter_message(text="Sorry, the selected pricing data was not found.")
            else:
                dispatcher.utter_message(text="Уучлаарай, сонгосон өгөгдлийн үнэ хүснэгтээс олдсонгүй.")
            return []

        total = gen_cr * gen_rate + maj_cr * maj_rate

        sender_id = tracker.sender_id
        try:
            with get_conn() as conn:
                ensure_tables(conn)
                user_id = ensure_user(conn, sender_id)
                conn.execute(
                    """
                    INSERT INTO tuition_runs(
                        user_id, admission_group, faculty,
                        general_credits, major_credits,
                        general_rate, major_rate,
                        total_tuition, created_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        str(group),
                        str(faculty),
                        float(gen_cr),
                        float(maj_cr),
                        float(gen_rate),
                        float(maj_rate),
                        float(total),
                        utc_now_iso(),
                    ),
                )
                conn.commit()
        except Exception as e:
            if is_english(tracker):
                dispatcher.utter_message(text=f"(DB save failed: {e})")
            else:
                dispatcher.utter_message(text=f"(DB хадгалалт амжилтгүй: {e})")

        def fmt(n: float) -> str:
            return f"{int(round(n)):,}"

        if is_english(tracker):
            group_label = {
                "before_2024_2025": "Before 2024–2025",
                "2024_2025": "2024–2025",
                "2025_2026": "2025–2026",
            }.get(str(group), str(group))
        else:
            group_label = {
                "before_2024_2025": "2024–2025 оноос өмнө",
                "2024_2025": "2024–2025",
                "2025_2026": "2025–2026",
            }.get(str(group), str(group))

        faculty_display = faculty
        if is_english(tracker):
            faculty_display = {
                "ШИНЖЛЭХ УХААНЫ СУРГУУЛЬ": "Science School",
                "МЭДЭЭЛЛИЙН ТЕХНОЛОГИ, ЭЛЕКТРОНИКИЙН СУРГУУЛЬ": "ICT & Electronics School",
                "ИНЖЕНЕР, ТЕХНОЛОГИЙН СУРГУУЛЬ": "Engineering & Technology School",
                "БИЗНЕСИЙН СУРГУУЛЬ": "Business School",
                "ХУУЛЬ ЗҮЙН СУРГУУЛЬ": "Law School",
                "УЛС ТӨР СУДЛАЛ, ОЛОН УЛСЫН ХАРИЛЦАА, НИЙТИЙН УДИРДЛАГЫН СУРГУУЛЬ": "Public Administration / International Relations",
                "ЗАВХАН АЙМАГ ДАХЬ БИЗНЕС, МЭДЭЭЛЛИЙН ТЕХНОЛОГИЙН СУРГУУЛЬ": "Zavkhan Campus (Business/ICT)",
                "ЗҮҮН БҮСИЙН СУРГУУЛЬ": "Eastern Region School",
                "БАРУУН БҮСИЙН СУРГУУЛЬ": "Western Region School",
            }.get(str(faculty), str(faculty))

        if is_english(tracker):
            msg = (
                f"Your selection:\n"
                f"- Admission: {group_label}\n"
                f"- School/Faculty: {faculty_display}\n\n"
                f"Calculation:\n"
                f"- General education: {gen_cr} cr × {fmt(gen_rate)} ₮ = {fmt(gen_cr * gen_rate)} ₮\n"
                f"- Major/specialization: {maj_cr} cr × {fmt(maj_rate)} ₮ = {fmt(maj_cr * maj_rate)} ₮\n\n"
                f"✅ Total tuition: {fmt(total)} ₮"
            )
        else:
            msg = (
                f"Таны сонголт:\n"
                f"- Элсэлт: {group_label}\n"
                f"- Бүрэлдэхүүн/салбар: {faculty_display}\n\n"
                f"Тооцоолол:\n"
                f"- Ерөнхий суурь: {gen_cr} кр × {fmt(gen_rate)} ₮ = {fmt(gen_cr * gen_rate)} ₮\n"
                f"- Мэргэжлийн суурь/мэргэших: {maj_cr} кр × {fmt(maj_rate)} ₮ = {fmt(maj_cr * maj_rate)} ₮\n\n"
                f"✅ Нийт төлөх төлбөр: {fmt(total)} ₮"
            )

        dispatcher.utter_message(text=msg)
        return []


class ActionSetAdmissionBefore(Action):
    def name(self) -> Text:
        return "action_set_admission_group_before_2024_2025"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("admission_group", "before_2024_2025")]


class ActionSetAdmission2024(Action):
    def name(self) -> Text:
        return "action_set_admission_group_2024_2025"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("admission_group", "2024_2025")]


class ActionSetAdmission2025(Action):
    def name(self) -> Text:
        return "action_set_admission_group_2025_2026"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("admission_group", "2025_2026")]


class ActionSetFacultyScience(Action):
    def name(self) -> Text:
        return "action_set_faculty_science"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("faculty", "ШИНЖЛЭХ УХААНЫ СУРГУУЛЬ")]


class ActionSetFacultyMTEE(Action):
    def name(self) -> Text:
        return "action_set_faculty_mtee"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("faculty", "МЭДЭЭЛЛИЙН ТЕХНОЛОГИ, ЭЛЕКТРОНИКИЙН СУРГУУЛЬ")]


class ActionSetFacultyEngineering(Action):
    def name(self) -> Text:
        return "action_set_faculty_engineering"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("faculty", "ИНЖЕНЕР, ТЕХНОЛОГИЙН СУРГУУЛЬ")]


class ActionSetFacultyBusiness(Action):
    def name(self) -> Text:
        return "action_set_faculty_business"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("faculty", "БИЗНЕСИЙН СУРГУУЛЬ")]


class ActionSetFacultyLaw(Action):
    def name(self) -> Text:
        return "action_set_faculty_law"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("faculty", "ХУУЛЬ ЗҮЙН СУРГУУЛЬ")]


class ActionSetFacultyPolitics(Action):
    def name(self) -> Text:
        return "action_set_faculty_politics"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("faculty", "УЛС ТӨР СУДЛАЛ, ОЛОН УЛСЫН ХАРИЛЦАА, НИЙТИЙН УДИРДЛАГЫН СУРГУУЛЬ")]


class ActionSetFacultyZavkhan(Action):
    def name(self) -> Text:
        return "action_set_faculty_zavkhan"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("faculty", "ЗАВХАН АЙМАГ ДАХЬ БИЗНЕС, МЭДЭЭЛЛИЙН ТЕХНОЛОГИЙН СУРГУУЛЬ")]


class ActionSetFacultyEast(Action):
    def name(self) -> Text:
        return "action_set_faculty_east"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("faculty", "ЗҮҮН БҮСИЙН СУРГУУЛЬ")]


class ActionSetFacultyWest(Action):
    def name(self) -> Text:
        return "action_set_faculty_west"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("faculty", "БАРУУН БҮСИЙН СУРГУУЛЬ")]


# -----------------------------
# GPA helpers
# -----------------------------

@dataclass
class GradeMap:
    letter: str
    gpa: float


def score_to_grade(score: float) -> GradeMap:
    s = float(score)
    if s >= 90:
        return GradeMap("A+", 4.0)
    if 85 <= s <= 89:
        return GradeMap("A-", 3.7)
    if 80 <= s <= 84:
        return GradeMap("B+", 3.3)
    if 75 <= s <= 79:
        return GradeMap("B", 3.0)
    if 70 <= s <= 74:
        return GradeMap("C-", 1.9)
    if 65 <= s <= 69:
        return GradeMap("C", 2.0)
    if 60 <= s <= 64:
        return GradeMap("D", 1.0)
    return GradeMap("F", 0.0)


class ValidateGpaForm(FormValidationAction):
    def name(self) -> str:
        return "validate_gpa_form"

    def validate_number_of_courses(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[str, Any]:
        try:
            n = int(float(slot_value))
        except Exception:
            if is_english(tracker):
                dispatcher.utter_message(text="Please enter a number. Example: 2")
            else:
                dispatcher.utter_message(text="Тоогоор оруулна уу. Жишээ: 2")
            return {"number_of_courses": None}

        if not (1 <= n <= 50):
            if is_english(tracker):
                dispatcher.utter_message(text="Number of courses must be between 1 and 50.")
            else:
                dispatcher.utter_message(text="Хичээлийн тоо 1-50 хооронд байх ёстой.")
            return {"number_of_courses": None}

        return {"number_of_courses": n, "current_course_index": 1, "courses": []}

    def validate_current_credit(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[str, Any]:
        try:
            c = float(slot_value)
        except Exception:
            if is_english(tracker):
                dispatcher.utter_message(text="Enter credits as a number. Example: 3")
            else:
                dispatcher.utter_message(text="Кредитийг тоогоор оруулна уу. Жишээ: 3")
            return {"current_credit": None}

        if not (0 < c <= 30):
            if is_english(tracker):
                dispatcher.utter_message(text="Credits must be between 0 and 30.")
            else:
                dispatcher.utter_message(text="Кредит 0-30 хооронд байх ёстой.")
            return {"current_credit": None}

        return {"current_credit": c}

    def validate_current_score(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: DomainDict,
    ) -> Dict[str, Any]:
        try:
            s = float(slot_value)
        except Exception:
            if is_english(tracker):
                dispatcher.utter_message(text="Enter the score as a number. Example: 95")
            else:
                dispatcher.utter_message(text="Дүнг тоогоор оруулна уу. Жишээ: 95")
            return {"current_score": None}

        if not (0 <= s <= 100):
            if is_english(tracker):
                dispatcher.utter_message(text="Score must be between 0 and 100.")
            else:
                dispatcher.utter_message(text="Дүн 0-100 хооронд байх ёстой.")
            return {"current_score": None}

        n = int(tracker.get_slot("number_of_courses") or 0)
        idx = int(float(tracker.get_slot("current_course_index") or 1))
        credit = float(tracker.get_slot("current_credit") or 0)

        courses = tracker.get_slot("courses") or []
        if not isinstance(courses, list):
            courses = []

        courses.append({"credit": credit, "score": s})
        next_idx = idx + 1

        if next_idx <= n:
            return {
                "courses": courses,
                "current_course_index": next_idx,
                "current_credit": None,
                "current_score": None,
            }

        return {"courses": courses, "current_score": s}


class ActionAskCurrentCredit(Action):
    def name(self) -> str:
        return "action_ask_current_credit"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[EventType]:
        idx = int(float(tracker.get_slot("current_course_index") or 1))
        if is_english(tracker):
            dispatcher.utter_message(text=f"📌 Course {idx} — how many credits? (e.g., 3)")
        else:
            dispatcher.utter_message(text=f"📌 {idx}-р хичээл — кредит хэд вэ? (ж: 3кр)")
        return []


class ActionAskCurrentScore(Action):
    def name(self) -> str:
        return "action_ask_current_score"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[EventType]:
        idx = int(float(tracker.get_slot("current_course_index") or 1))
        if is_english(tracker):
            dispatcher.utter_message(text=f"📝 Course {idx} — what's the score? (0–100)")
        else:
            dispatcher.utter_message(text=f"📝 {idx}-р хичээл — дүн хэд вэ? (0–100)")
        return []


class ActionCalculateGpa(Action):
    def name(self) -> str:
        return "action_calculate_gpa"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[EventType]:
        courses = tracker.get_slot("courses") or []
        if not courses:
            if is_english(tracker):
                dispatcher.utter_message(text="Course information is missing. Let's start again.")
            else:
                dispatcher.utter_message(text="Хичээлийн мэдээлэл алга байна. Дахин эхлүүлье.")
            return [
                SlotSet("number_of_courses", None),
                SlotSet("current_course_index", 1),
                SlotSet("current_credit", None),
                SlotSet("current_score", None),
                SlotSet("courses", []),
            ]

        total_credits = 0.0
        total_points = 0.0
        lines: List[str] = []

        for i, c in enumerate(courses, start=1):
            cr = float(c["credit"])
            sc = float(c["score"])
            g = score_to_grade(sc)

            total_credits += cr
            total_points += cr * g.gpa

            lines.append(f"{i}. {cr:g}кр - {sc:g}% → {g.letter} ({g.gpa:.1f})")

        gpa = total_points / total_credits if total_credits > 0 else 0.0

        if is_english(tracker):
            msg = (
                "📊 Your grade breakdown:\n"
                + "\n".join([f"  {ln}" for ln in lines])
                + f"\n\n✅ Total credits: {total_credits:g}"
                + f"\n⭐ GPA: {gpa:.2f}"
            )
        else:
            msg = (
                "📊 Таны дүнгийн задаргаа:\n"
                + "\n".join([f"  {ln}" for ln in lines])
                + f"\n\n✅ Нийт кредит: {total_credits:g}"
                + f"\n⭐ Нийт GPA: {gpa:.2f}"
            )

        dispatcher.utter_message(text=msg)

        return [
            SlotSet("number_of_courses", None),
            SlotSet("current_course_index", 1),
            SlotSet("current_credit", None),
            SlotSet("current_score", None),
            SlotSet("courses", []),
        ]


# -----------------------------
# Location helpers
# -----------------------------

NUM_ONLY_RE = re.compile(r"^\s*(\d{1,2})\s*$")
BAIR_RE = re.compile(r"^\s*(\d{1,2})\s*[-‐-–—]?\s*р?\s*байр\s*$", re.IGNORECASE)
BAIR_LOOSE_RE = re.compile(r"(\d{1,2})\s*[-‐-–—]?\s*р?\s*бай[аa]р", re.IGNORECASE)

FORBIDDEN = {
    ("dorm", 4),
    ("class", 6),
}


def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("ё", "е")
    s = re.sub(r"[“”\"'`]", "", s)
    s = re.sub(r"[,\.\(\)\[\]\{\}]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def detect_kind(text: str) -> Optional[str]:
    t = norm(text)
    if "дотуур" in t or "dorm" in t:
        return "dorm"
    if "хичээл" in t or "хичээлийн" in t or "сургуулийн" in t or "academic" in t:
        return "class"
    return None


def extract_number(text: str) -> Optional[int]:
    t = text.strip()
    m = NUM_ONLY_RE.match(t)
    if m:
        return int(m.group(1))
    m = BAIR_RE.match(t)
    if m:
        return int(m.group(1))
    m = BAIR_LOOSE_RE.search(t)
    if m:
        return int(m.group(1))
    return None


def is_list_request(text: str) -> bool:
    t = norm(text)
    return t in {"байршлууд", "жагсаалт", "locations", "list", "байршилууд"}


def load_places() -> Tuple[Dict[str, Dict[str, Any]], Dict[Tuple[str, int], Dict[str, Any]], List[Dict[str, Any]]]:
    path = Path(__file__).resolve().parent / "locations.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_places: List[Dict[str, Any]] = data.get("places", []) if isinstance(data, dict) else []

    places: List[Dict[str, Any]] = []
    for p in raw_places:
        if not isinstance(p, dict):
            continue
        kind = str(p.get("kind") or "")
        num = p.get("number")
        if isinstance(num, int) and (kind, num) in FORBIDDEN:
            continue
        places.append(p)

    alias_index: Dict[str, Dict[str, Any]] = {}
    kind_num_index: Dict[Tuple[str, int], Dict[str, Any]] = {}

    for p in places:
        aliases = p.get("aliases", []) or []
        for a in aliases:
            alias_index[norm(str(a))] = p
        kind = p.get("kind")
        num = p.get("number")
        if kind and isinstance(num, int):
            kind_num_index[(str(kind), num)] = p

    return alias_index, kind_num_index, places


_ALIAS_INDEX, _KIND_NUM_INDEX, _ALL_PLACES = load_places()


def say_place(dispatcher: CollectingDispatcher, place: Dict[str, Any], english: bool = False) -> None:
    title = place.get("title", "Байршил")
    url = (place.get("url") or "").strip()
    if url:
        dispatcher.utter_message(f"{title}\n{url}")
    else:
        if english:
            dispatcher.utter_message(
                f"{title}\n(⚠️ Google Maps link is missing in locations.yml — add the link and try again.)"
            )
        else:
            dispatcher.utter_message(
                f"{title}\n(⚠️ Google Maps линк одоогоор locations.yml дээр байхгүй байна — линкээ нэмээд дахин туршаарай.)"
            )


class ActionSendLocation(Action):
    def name(self) -> str:
        return "action_send_location"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        text = (tracker.latest_message.get("text") or "").strip()
        latest_intent = (tracker.latest_message.get("intent") or {}).get("name")

        pending_number = tracker.get_slot("pending_number")
        place_type = tracker.get_slot("place_type")

        if latest_intent == "choose_place_type" and pending_number:
            chosen_kind = detect_kind(text) or (place_type if place_type in {"class", "dorm"} else None)
            if chosen_kind is None:
                if is_english(tracker):
                    dispatcher.utter_message("Please answer with “academic building” or “dormitory”.")
                else:
                    dispatcher.utter_message("“хичээлийн байр” эсвэл “дотуур байр” гэж хариулаарай 🙂")
                return []

            try:
                num = int(str(pending_number))
            except Exception:
                num = None

            if num is not None:
                if (chosen_kind, num) in FORBIDDEN:
                    if is_english(tracker):
                        dispatcher.utter_message("Sorry, that building information is not available in this bot.")
                    else:
                        dispatcher.utter_message("Уучлаарай, тэр байрны мэдээлэл энэ бот дээр байхгүй байна.")
                    return [SlotSet("pending_number", None), SlotSet("place_type", chosen_kind)]

                place = _KIND_NUM_INDEX.get((chosen_kind, num))
                if place:
                    say_place(dispatcher, place, english=is_english(tracker))
                    return [SlotSet("pending_number", None), SlotSet("place_type", chosen_kind)]

            if is_english(tracker):
                dispatcher.utter_message("Sorry, no location found for that number. Try searching by name.")
            else:
                dispatcher.utter_message("Уучлаарай, тэр дугаартай байршил олдсонгүй. Дахиад нэрээр нь бичээд үзээрэй.")
            return [SlotSet("pending_number", None)]

        if is_list_request(text):
            if is_english(tracker):
                lines = ["Available locations:"]
            else:
                lines = ["Боломжтой байршлууд:"]
            for p in _ALL_PLACES:
                title = p.get("title")
                if title:
                    lines.append(f"• {title}")
            dispatcher.utter_message("\n".join(lines))
            return []

        kind = detect_kind(text)
        num = extract_number(text)

        if num is not None and kind is None and (NUM_ONLY_RE.match(text) or BAIR_RE.match(text) or BAIR_LOOSE_RE.search(text)):
            dispatcher.utter_message(response="utter_ask_place_type")
            return [SlotSet("pending_number", str(num))]

        if num is not None and kind in {"class", "dorm"}:
            if (kind, num) in FORBIDDEN:
                if is_english(tracker):
                    dispatcher.utter_message("Sorry, that building information is not available in this bot.")
                else:
                    dispatcher.utter_message("Уучлаарай, тэр байрны мэдээлэл энэ бот дээр байхгүй байна.")
                return [SlotSet("place_type", kind), SlotSet("pending_number", None)]

            place = _KIND_NUM_INDEX.get((kind, num))
            if place:
                say_place(dispatcher, place, english=is_english(tracker))
                return [SlotSet("place_type", kind), SlotSet("pending_number", None)]

            if is_english(tracker):
                dispatcher.utter_message("Sorry, no location found for that number. Try searching by name.")
            else:
                dispatcher.utter_message("Уучлаарай, тэр дугаартай байршил олдсонгүй. Дахиад нэрээр нь бичээд үзээрэй.")
            return []

        ntext = norm(text)

        place = _ALIAS_INDEX.get(ntext)
        if place:
            say_place(dispatcher, place, english=is_english(tracker))
            return []

        for a_norm, p in _ALIAS_INDEX.items():
            if a_norm and a_norm in ntext:
                say_place(dispatcher, p, english=is_english(tracker))
                return []

        if is_english(tracker):
            dispatcher.utter_message("Sorry, I couldn't find that location 😅 Type “locations” to see the list.")
        else:
            dispatcher.utter_message("Уучлаарай, тэр байршлыг олсонгүй 😅 “байршлууд” гэж бичээд жагсаалтыг хараарай.")
        return []
