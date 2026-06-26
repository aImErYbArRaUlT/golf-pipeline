{#
  Use the configured schema verbatim instead of dbt's default behaviour of
  prefixing it with the target schema. This lets a model's `+schema` be the
  exact BigQuery dataset (e.g. dev_gold), matching the <env>_<layer> scheme
  that OpenTofu provisions. With no custom schema, fall back to the target's
  dataset (the profile's `dataset:`, i.e. <env>_silver).
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
