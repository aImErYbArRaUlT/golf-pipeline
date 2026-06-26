{#
  Generic range test: fails for any non-null value outside [min_value, max_value].
  Used as a data contract on conformed metrics (e.g. ball speed, smash factor).
  Custom (rather than a package) to keep the project dependency-free.
#}
{% test between(model, column_name, min_value, max_value) %}

select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and ({{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }})

{% endtest %}
