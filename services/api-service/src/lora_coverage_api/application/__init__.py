"""Application layer — business logic + repository protocols.

CHỈ phụ thuộc domain. KHÔNG import infrastructure (enforced by import-linter).
KHÔNG mention chuỗi infra: "postgres", "redis", "valkey", "s3", "stage_4",
"GiST", "BRIN" (enforced by CI grep).
"""
