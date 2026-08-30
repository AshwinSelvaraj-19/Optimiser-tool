"""
Cleanup data models — structured types for scan results, cleanup operations, and sessions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional
import uuid


class CleanupStatus(Enum):
    """Status of a cleanup item or operation."""
    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    SAFE = "SAFE"
    REQUIRES_ADMIN = "REQUIRES_ADMIN"
    SELECTED = "SELECTED"
    SKIPPED = "SKIPPED"
    CLEANED = "CLEANED"
    FAILED = "FAILED"
    VERIFIED = "VERIFIED"
    RECOMMENDATION_ONLY = "RECOMMENDATION_ONLY"


class CleanupCategory(Enum):
    """Category of cleanup target."""
    USER_TEMP = "User Temp"
    SYSTEM_TEMP = "System Temp"
    RECYCLE_BIN = "Recycle Bin"
    SHADER_CACHE = "Shader Cache"
    APPLICATION_CACHE = "Application Cache"


@dataclass
class CleanupItem:
    """A single detected cleanup target."""
    id: str = ""
    name: str = ""
    category: CleanupCategory = CleanupCategory.USER_TEMP
    description: str = ""
    path: str = ""
    detected_size: int = 0        # Total size in bytes
    removable_size: int = 0       # Actually removable size in bytes
    file_count: int = 0           # Total files
    removable_file_count: int = 0 # Files that can be deleted
    skipped_file_count: int = 0   # Locked/protected files
    risk: str = "LOW"             # LOW, MEDIUM, HIGH
    available: bool = False
    selected: bool = False
    requires_admin: bool = False
    can_delete: bool = False
    reason: str = ""
    status: CleanupStatus = CleanupStatus.NOT_AVAILABLE

    def __post_init__(self):
        if not self.id:
            self.id = f"cleanup_{uuid.uuid4().hex[:8]}"

    @property
    def size_display(self) -> str:
        """Human-readable size."""
        return format_bytes(self.detected_size)

    @property
    def removable_display(self) -> str:
        """Human-readable removable size."""
        return format_bytes(self.removable_size)


@dataclass
class CleanupResult:
    """Result of cleaning a single item."""
    item_id: str = ""
    item_name: str = ""
    success: bool = False
    files_deleted: int = 0
    bytes_freed: int = 0
    files_failed: int = 0
    bytes_failed: int = 0
    duration_seconds: float = 0.0
    message: str = ""
    verification_status: CleanupStatus = CleanupStatus.FAILED


@dataclass
class CleanupSessionResult:
    """Result of an entire cleanup session."""
    session_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    scanned_items: int = 0
    selected_items: int = 0
    successful_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0
    bytes_freed: int = 0
    files_deleted: int = 0
    verification_passed: int = 0
    verification_failed: int = 0
    results: List[CleanupResult] = field(default_factory=list)
    message: str = ""

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"cleanup_{uuid.uuid4().hex[:8]}"

    @property
    def bytes_freed_display(self) -> str:
        return format_bytes(self.bytes_freed)

    @property
    def success(self) -> bool:
        return self.failed_items == 0 and self.successful_items > 0


def format_bytes(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    if size_bytes < 0:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
