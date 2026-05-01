```markdown
BEGIN_FILE claude_worklog/agent_supervisor/ollama_context/012a_database_sch[64D[K
claude_worklog/agent_supervisor/ollama_context/012a_database_schema_contextclaude_worklog/agent_supervisor/ollama_context/012a_database_schma_context.md

# Database Schema Context

## Current Lineage Gaps
- Missing relationships between tables identified in 06_FEATURE_DATA_FLOW_G[22D[K
06_FEATURE_DATA_FLOW_GAPS.
- Lack of comprehensive schema documentation for new features detailed in 0[1D[K
03_DATABASE_SCHEMA.

## Required FK/Index/Nullability Constraints
- Add foreign key constraints to:
  - `orders` referencing `customers`
  - `order_items` referencing `orders` and `products`
- Create indexes on:
  - `customer_id` in `orders`
  - `product_id` in `order_items`
- Ensure nullability:
  - All date fields (`created_at`, `updated_at`) are NOT NULL.

## Attribution Rejection Requirements
- Reject any feature requests without detailed schema changes as per 03_DAT[6D[K
03_DATABASE_SCHEMA.
- Features requiring data lineage without corresponding schema updates will[4D[K
will be deferred until addressed.

## Acceptance Checklist
- [ ] Lineage gaps resolved by identifying and documenting new relationship[12D[K
relationships.
- [ ] Foreign key constraints added for all required references.
- [ ] Indexes created on critical fields for performance improvements.
- [ ] Nullability enforced on date fields across the database.

END_FILE
```

