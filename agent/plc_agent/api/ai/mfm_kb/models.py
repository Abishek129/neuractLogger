# mypy: ignore-errors
"""
Pydantic models for the MFM Knowledge Base.

Covers: KB entry structure, index entries, and REST request/response models.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# KB Entry models
# ---------------------------------------------------------------------------

class RegisterEntry(BaseModel):
    """A single register in the MFM device register map."""
    address: int
    count: int = 1
    parameter: str
    data_type: str              # float32, uint16, int32, uint32, int16
    unit: str = ""
    scale: float = 1.0
    access: str = "read"        # read | write | read_write
    typical_range: list[float] = Field(default_factory=list)
    source_page: Optional[int] = None


class IdentificationBlock(BaseModel):
    """Identification register used for device fingerprinting."""
    model_config = {"populate_by_name": True}

    register_address: int = Field(alias="register")
    expected_value: str
    description: str = ""


class KBEntry(BaseModel):
    """Full knowledge base entry for one MFM model."""
    manufacturer: str
    model: str
    protocol: str               # modbus_tcp, modbus_rtu, opcua
    byte_order: str = "big_endian"
    identification: Optional[IdentificationBlock] = None
    registers: list[RegisterEntry] = Field(default_factory=list)
    quirks: list[str] = Field(default_factory=list)
    source_document: Optional[str] = None
    extraction_date: Optional[str] = None
    verified_by_engineer: bool = False
    version: int = 1


# ---------------------------------------------------------------------------
# Index models
# ---------------------------------------------------------------------------

class IndexEntry(BaseModel):
    """One entry in the KB index manifest."""
    model: str
    file: str                   # relative filename in mfm_kb/
    version: int = 1
    source_doc: Optional[str] = None
    extraction_date: Optional[str] = None
    verified: bool = False


class KBIndex(BaseModel):
    """The full KB index (index.json)."""
    models: dict[str, IndexEntry] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# REST request / response models
# ---------------------------------------------------------------------------

class KBListItem(BaseModel):
    model: str
    manufacturer: str = ""
    protocol: str = ""
    register_count: int = 0
    verified: bool = False


class KBListResponse(BaseModel):
    models: list[KBListItem]
    count: int


class KBEntryResponse(BaseModel):
    entry: KBEntry
    warnings: list[str] = Field(default_factory=list)


class KBUploadResponse(BaseModel):
    filename: str
    size_bytes: int
    pages: int
    message: str


class KBCreateUpdateRequest(BaseModel):
    entry: KBEntry


class KBCreateUpdateResponse(BaseModel):
    model: str
    version: int
    file: str
    message: str


class KBDeleteResponse(BaseModel):
    model: str
    message: str
