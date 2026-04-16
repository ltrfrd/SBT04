from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from backend.config import settings


PHASE1 = "phase1"
PHASE2 = "phase2"
CAPTURE_TOKEN_SESSION_KEY = "posttrip_capture_tokens"

PHOTO_TYPE_PHASE1_REAR_TO_FRONT = "phase1_rear_to_front"
PHOTO_TYPE_PHASE2_REAR_TO_FRONT = "phase2_rear_to_front"
PHOTO_TYPE_PHASE2_CLEARED_SIGN = "phase2_cleared_sign"

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # Cap per captured image to keep runtime uploads bounded
ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
PIL_FORMAT_TO_MIME_TYPE = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


@dataclass(frozen=True)
class PhotoRequirement:
    phase: str
    photo_type: str
    field_name: str
    label: str


PHASE_PHOTO_REQUIREMENTS: dict[str, tuple[PhotoRequirement, ...]] = {
    PHASE1: (
        PhotoRequirement(
            phase=PHASE1,
            photo_type=PHOTO_TYPE_PHASE1_REAR_TO_FRONT,
            field_name="phase1_rear_to_front_image",
            label="rear of bus photo",
        ),
    ),
    PHASE2: (
        PhotoRequirement(
            phase=PHASE2,
            photo_type=PHOTO_TYPE_PHASE2_REAR_TO_FRONT,
            field_name="phase2_rear_to_front_image",
            label="final rear of bus photo",
        ),
        PhotoRequirement(
            phase=PHASE2,
            photo_type=PHOTO_TYPE_PHASE2_CLEARED_SIGN,
            field_name="phase2_cleared_sign_image",
            label="cleared sign photo",
        ),
    ),
}


def get_required_photos_for_phase(phase: str) -> tuple[PhotoRequirement, ...]:
    requirements = PHASE_PHOTO_REQUIREMENTS.get(phase)
    if requirements is None:
        raise ValueError(f"Unsupported post-trip phase: {phase}")
    return requirements


def get_or_create_capture_token(session: dict, *, run_id: int, create_token) -> str:
    token_map = session.get(CAPTURE_TOKEN_SESSION_KEY)
    if not isinstance(token_map, dict):
        token_map = {}
        session[CAPTURE_TOKEN_SESSION_KEY] = token_map

    run_key = str(run_id)
    token = token_map.get(run_key)
    if not token:
        token = create_token()
        token_map[run_key] = token
        session[CAPTURE_TOKEN_SESSION_KEY] = token_map
    return token


def require_valid_capture_token(*, session: dict, run_id: int, capture_token: str) -> None:
    token_map = session.get(CAPTURE_TOKEN_SESSION_KEY)
    expected_token = token_map.get(str(run_id)) if isinstance(token_map, dict) else None
    if not expected_token or capture_token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid photo submission",
        )


def build_missing_photo_detail(phase: str, uploads_by_field: dict[str, UploadFile | None]) -> str | None:
    missing_labels = [
        requirement.label
        for requirement in get_required_photos_for_phase(phase)
        if uploads_by_field.get(requirement.field_name) is None
    ]
    if not missing_labels:
        return None
    if len(missing_labels) == 1:
        return f"Required photo missing: {missing_labels[0]}"
    return f"Required photo missing: {', '.join(missing_labels)}"


def get_photo_storage_directory(*, run_id: int, phase: str) -> Path:
    return Path(settings.MEDIA_ROOT) / "posttrip" / f"run_{run_id}" / phase


def remove_relative_media_file(relative_path: str | None) -> None:
    if not relative_path:
        return

    absolute_path = Path(settings.MEDIA_ROOT) / relative_path
    try:
        absolute_path.unlink(missing_ok=True)
    except OSError:
        return


def _reject_invalid_image(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _read_upload_bytes(upload: UploadFile) -> bytes:
    data = upload.file.read()
    if not data:
        raise _reject_invalid_image(f"{upload.filename or 'Image'} is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise _reject_invalid_image(f"{upload.filename or 'Image'} exceeds the 8 MB size limit")
    return data


def _detect_valid_image(data: bytes) -> tuple[str, str]:
    image_format = ""
    if data.startswith(b"\xff\xd8\xff"):
        image_format = "JPEG"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        image_format = "PNG"
    elif len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        image_format = "WEBP"
    else:
        raise _reject_invalid_image("Uploaded file is not a valid image")

    detected_mime_type = PIL_FORMAT_TO_MIME_TYPE.get(image_format)
    if detected_mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise _reject_invalid_image("Only JPEG, PNG, and WEBP images are accepted")

    return image_format, detected_mime_type


def save_camera_upload(*, upload: UploadFile, run_id: int, phase: str, photo_type: str) -> dict[str, object]:
    data = _read_upload_bytes(upload)
    _, detected_mime_type = _detect_valid_image(data)

    declared_mime_type = (upload.content_type or "").lower()
    if declared_mime_type and declared_mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise _reject_invalid_image("Only JPEG, PNG, and WEBP images are accepted")

    extension = ALLOWED_IMAGE_MIME_TYPES[detected_mime_type]
    directory = get_photo_storage_directory(run_id=run_id, phase=phase)
    os.makedirs(directory, exist_ok=True)

    relative_path = Path("posttrip") / f"run_{run_id}" / phase / f"{photo_type}_{uuid4().hex}{extension}"
    absolute_path = Path(settings.MEDIA_ROOT) / relative_path
    absolute_path.write_bytes(data)

    return {
        "file_path": relative_path.as_posix(),
        "mime_type": detected_mime_type,
        "file_size_bytes": len(data),
        "source": "camera",
        "captured_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }
