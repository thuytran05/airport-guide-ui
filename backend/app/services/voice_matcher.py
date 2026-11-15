import re
import unicodedata
from typing import List, Dict, Any, Optional

def normalize_text(text: str) -> str:
    """Chuẩn hóa văn bản: chữ thường, chuẩn NFC, bỏ dấu câu và khoảng trắng thừa"""
    if not text:
        return ""
    text = unicodedata.normalize('NFC', text.strip().lower())
    # Thay thế các dấu câu bằng khoảng trắng
    text = re.sub(r'[^\w\s]', ' ', text)
    return " ".join(text.split())

def match_destination_from_transcript(transcript: str, destinations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Đối chiếu văn bản nhận dạng giọng nói với danh sách điểm đến:
    - Trả về status='MATCHED' nếu khớp đúng duy nhất 1 điểm đến.
    - Trả về status='NO_MATCH' nếu không tìm thấy điểm đến nào phù hợp.
    - Trả về status='AMBIGUOUS' nếu tìm thấy nhiều hơn 1 điểm đến khớp hoặc trùng tên.
    """
    if not transcript or not destinations:
        return {
            "status": "NO_MATCH",
            "destination": None,
            "matched_candidates": []
        }

    norm_transcript = normalize_text(transcript)
    if not norm_transcript:
        return {
            "status": "NO_MATCH",
            "destination": None,
            "matched_candidates": []
        }

    # Từ dừng tiếng Việt phổ biến trong khẩu lệnh dẫn đường
    stop_words = {
        "hãy", "dẫn", "tôi", "cho", "đi", "đến", "tới", "ở", "đâu", "muốn",
        "nhờ", "bạn", "robot", "xin", "vui", "lòng", "ra", "vào", "tìm"
    }
    words_in_transcript = set(norm_transcript.split()) - stop_words

    matched = []

    # 1. Khớp chính xác tên hoặc ID trọn vẹn
    for d in destinations:
        d_id = normalize_text(str(d.get("id", "")))
        d_name = normalize_text(str(d.get("name", "")))

        # Khớp toàn bộ chuỗi
        if d_name and (d_name == norm_transcript or f" {d_name} " in f" {norm_transcript} "):
            matched.append(d)
            continue
        if d_id and (d_id == norm_transcript or f" {d_id} " in f" {norm_transcript} "):
            matched.append(d)
            continue

    # 2. Khớp theo số thứ tự và từ khóa chính (ví dụ "Cổng 1", "Cổng số 1" khớp "Cổng khởi hành số 1")
    if not matched:
        numbers_in_t = re.findall(r'\d+', norm_transcript)
        for d in destinations:
            d_id = normalize_text(str(d.get("id", "")))
            d_name = normalize_text(str(d.get("name", "")))
            numbers_in_d = re.findall(r'\d+', d_name) + re.findall(r'\d+', d_id)

            if numbers_in_t and numbers_in_d and numbers_in_t == numbers_in_d:
                key_keywords = {"cổng", "gate", "cửa", "quầy", "desk", "khu"}
                has_key_in_t = any(k in norm_transcript for k in key_keywords)
                has_key_in_d = any(k in d_name or k in d_id for k in key_keywords)
                if has_key_in_t and has_key_in_d:
                    matched.append(d)
                    continue

            # 3. Khớp tập con từ khóa (ví dụ "vệ sinh" khớp "Khu vệ sinh công cộng", "cổng" khớp cả cổng 1 và cổng 2)
            d_words = (set(d_name.split()) | set(d_id.split("_"))) - stop_words
            if d_words and d_words.issubset(words_in_transcript):
                matched.append(d)
            elif words_in_transcript and words_in_transcript.issubset(d_words):
                matched.append(d)

    # Loại bỏ các ứng viên trùng ID
    seen_ids = set()
    unique_candidates = []
    for d in matched:
        did = d.get("id")
        if did and did not in seen_ids:
            seen_ids.add(did)
            unique_candidates.append(d)

    if len(unique_candidates) == 1:
        return {
            "status": "MATCHED",
            "destination": unique_candidates[0],
            "matched_candidates": unique_candidates
        }
    elif len(unique_candidates) > 1:
        return {
            "status": "AMBIGUOUS",
            "destination": None,
            "matched_candidates": unique_candidates,
            "count": len(unique_candidates)
        }
    else:
        return {
            "status": "NO_MATCH",
            "destination": None,
            "matched_candidates": []
        }
