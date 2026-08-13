import json
import os
import subprocess
import time
import sys

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

START_SEAT = 2910001
END_SEAT = 2980000
BASE_URL = "https://nategafany.com/api/result.php"

STATE_FILE = "checkpoint.json"
RESULTS_FILE = "student_results.json"

MAX_RUNTIME_MIN = float(os.environ.get("MAX_RUNTIME_MIN", "330"))
REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "1.5"))
SAVE_EVERY = int(os.environ.get("SAVE_EVERY", "100"))


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, capture_output=True, text=True)


def in_git_repo():
    try:
        return git("rev-parse", "--is-inside-work-tree", check=False).returncode == 0
    except Exception:
        return False


def save_state(state, commit):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

    sorted_results = sorted(state["results"], key=lambda x: x["percentage"], reverse=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_results, f, ensure_ascii=False, indent=4)

    if not commit:
        return

    if not in_git_repo():
        print("(لا يوجد مستودع git هنا — تم حفظ الملفات فقط دون commit)")
        return

    git("add", "-A")
    changed = git("diff", "--cached", "--quiet", check=False)
    if changed.returncode != 0:
        branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        git("commit", "-m", f"checkpoint: seat {state.get('last_done_seat')} - {len(state['results'])} results")
        for _ in range(5):
            pull = git("pull", "--rebase", "origin", branch, check=False)
            if pull.returncode != 0:
                time.sleep(10)
                continue
            push = git("push", "origin", branch, check=False)
            if push.returncode == 0:
                break
            time.sleep(10)


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"next_seat": START_SEAT, "last_done_seat": None, "results": []}
    with open(STATE_FILE, encoding="utf-8") as f:
        state = json.load(f)
    seen = {}
    deduped = []
    for r in state.get("results", []):
        sn = r.get("seat_no")
        if sn not in seen:
            seen[sn] = True
            deduped.append(r)
    state["results"] = deduped
    return state


def main():
    state = load_state()
    seat = int(state.get("next_seat", START_SEAT))

    if state.get("done") or seat > END_SEAT:
        print(f"المسح مكتمل بالفعل (next_seat={seat}). لا شيء لفعله.")
        return

    start_time = time.monotonic()
    counted = 0
    known = {r["seat_no"] for r in state["results"]}

    while seat <= END_SEAT:
        if time.monotonic() - start_time > MAX_RUNTIME_MIN * 60:
            print(f"\n⏰ انتهى وقت الجوب ({MAX_RUNTIME_MIN} دقيقة). حفظ التقدم والخروج...")
            state["next_seat"] = seat
            state["last_done_seat"] = seat - 1
            save_state(state, commit=True)
            print(f"تم الحفظ. آخر رقم تم التأكد منه: {seat - 1}")
            return

        if seat in known:
            print(f"↩ رقم الجلوس {seat} موجود مسبقًا — تخطي.")
            seat += 1
            continue

        seat_no = seat
        success = False
        while not success:
            try:
                response = requests.get(BASE_URL, params={"seat_no": seat_no}, timeout=10)

                if response.status_code == 429:
                    print(f"⚠️ تم الوصول للحد الأقصى عند الرقم {seat_no}. انتظار 10 ثوانٍ...")
                    time.sleep(10)
                    continue

                if response.status_code == 200:
                    payload = response.json()
                    if payload.get("status") == "success" and "data" in payload and payload["data"].get("name"):
                        data = payload["data"]
                        pct_str = data.get("percentage", "0%")
                        student_info = {
                            "seat_no": seat_no,
                            "name": data.get("name", "غير معروف"),
                            "school": data.get("school", "-"),
                            "division": data.get("division", "-"),
                            "specialization": data.get("specialization", "-"),
                            "score": data.get("total", "0"),
                            "grade": data.get("grade", "-"),
                            "percentage": float(pct_str.replace("%", "").strip()),
                            "pct_str": pct_str,
                        }
                        state["results"].append(student_info)
                        print(f"✓ تم سحب {seat_no}: {student_info['name']} | {student_info['score']} ({pct_str}) | {student_info['division']} - {student_info['specialization']} | {student_info['school']}")
                    else:
                        print(f"✗ لا توجد بيانات لرقم الجلوس {seat_no}")
                    success = True
                elif response.status_code == 404:
                    print(f"✗ رقم الجلوس {seat_no} غير موجود (404)")
                    success = True
                else:
                    print(f"✗ خطأ رمز ({response.status_code}) لرقم الجلوس {seat_no}")
                    success = True

            except Exception as e:
                print(f"⚠️ خطأ في الاتصال عند الرقم {seat_no}: {e}. إعادة المحاولة بعد 3 ثوانٍ...")
                time.sleep(3)

        seat += 1
        counted += 1

        if counted >= SAVE_EVERY:
            state["next_seat"] = seat
            state["last_done_seat"] = seat - 1
            save_state(state, commit=True)
            counted = 0

        time.sleep(REQUEST_DELAY)

    state["next_seat"] = seat
    state["last_done_seat"] = seat - 1
    state["done"] = True
    save_state(state, commit=True)
    print("\n✅ اكتمل المسح بالكامل!")
    print(f"إجمالي الطلاب: {len(state['results'])}")


if __name__ == "__main__":
    main()