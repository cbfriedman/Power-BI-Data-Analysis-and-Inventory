"""Vendor file ingestion: readers, profile-driven extraction, validation.

Empty at scaffold stage; built in phases 5 and 6.

Two rules govern everything added here:
* the raw uploaded file is persisted byte-for-byte before parsing begins
  (ADR 0004);
* pandas is never used, and every field is read as ``str`` with no type
  inference, because inference silently destroys leading zeros in UPCs and
  vendor SKUs (ADR 0008, risk R2).
"""
