import pytest
from dbt.tests.adapter.constraints.test_constraints import (
    BaseTableConstraintsColumnsEqual,
    BaseViewConstraintsColumnsEqual,
    BaseIncrementalConstraintsColumnsEqual,
    BaseConstraintsRuntimeDdlEnforcement,
    BaseConstraintsRollback,
    BaseIncrementalConstraintsRuntimeDdlEnforcement,
    BaseIncrementalConstraintsRollback,
)
from dbt.tests.adapter.constraints.fixtures import (
    my_model_sql,
    my_model_wrong_order_sql,
    my_model_wrong_name_sql,
    model_schema_yml,
    my_model_view_wrong_order_sql,
    my_model_view_wrong_name_sql,
    my_model_incremental_wrong_order_sql,
    my_model_incremental_wrong_name_sql,
    my_incremental_model_sql,
    incremental_foreign_key_model_raw_numbers_sql,
    incremental_foreign_key_model_stg_numbers_sql,
)
from dbt.tests.util import (
    run_dbt,
    write_file,
    read_file,
)

# constraints are enforced via 'alter' statements that run after table creation
_expected_sql_spark = """
create or replace table <model_identifier>
    using delta
    as
select
  id,
  color,
  date_day
from
( select
    'blue' as color,
    1 as id,
    '2019-01-01' as date_day ) as model_subq
"""

# Different on Spark:
# - does not support a data type named 'text'
# (TODO handle this in the base test classes using string_type
constraints_yml = model_schema_yml.replace("text", "string").replace("primary key", "")


class DatabricksHTTPSetup:
    @pytest.fixture
    def string_type(self):
        return "string"

    @pytest.fixture
    def int_type(self):
        return "int"

    @pytest.fixture
    def schema_int_type(self, int_type):
        return "int"

    @pytest.fixture
    def data_types(self, schema_int_type, int_type, string_type):
        # sql_column_value, schema_data_type, error_data_type
        return [
            # TODO: the int type is tricky to test in test__constraints_wrong_column_data_type
            # without a schema_string_type to override.
            # uncomment the line below once
            # https://github.com/dbt-labs/dbt-core/issues/7121 is resolved
            # ['1', schema_int_type, int_type],
            ['"1"', "string", string_type],
            ["true", "boolean", "boolean"],
            ['array("1","2","3")', "array<string>", "array"],
            ["array(1,2,3)", "array<int>", "array"],
            ["cast('2019-01-01' as date)", "date", "date"],
            ["cast('2019-01-01' as timestamp)", "timestamp", "timestamp"],
            ["cast(1.0 AS DECIMAL(4, 2))", "decimal", "decimal"],
        ]


@pytest.mark.skip_profile("databricks_cluster")
class TestSparkTableConstraintsColumnsEqualDatabricksHTTP(
    DatabricksHTTPSetup, BaseTableConstraintsColumnsEqual
):
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "my_model_wrong_order.sql": my_model_wrong_order_sql,
            "my_model_wrong_name.sql": my_model_wrong_name_sql,
            "constraints_schema.yml": constraints_yml,
        }


@pytest.mark.skip_profile("databricks_cluster")
class TestSparkViewConstraintsColumnsEqualDatabricksHTTP(
    DatabricksHTTPSetup, BaseViewConstraintsColumnsEqual
):
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "my_model_wrong_order.sql": my_model_view_wrong_order_sql,
            "my_model_wrong_name.sql": my_model_view_wrong_name_sql,
            "constraints_schema.yml": constraints_yml,
        }


@pytest.mark.skip_profile("databricks_cluster")
class TestSparkIncrementalConstraintsColumnsEqualDatabricksHTTP(
    DatabricksHTTPSetup, BaseIncrementalConstraintsColumnsEqual
):
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "my_model_wrong_order.sql": my_model_incremental_wrong_order_sql,
            "my_model_wrong_name.sql": my_model_incremental_wrong_name_sql,
            "constraints_schema.yml": constraints_yml,
        }


class BaseSparkConstraintsDdlEnforcementSetup:
    @pytest.fixture(scope="class")
    def project_config_update(self):
        return {
            "models": {
                "+file_format": "delta",
            }
        }

    @pytest.fixture(scope="class")
    def expected_sql(self):
        return _expected_sql_spark


@pytest.mark.skip_profile("databricks_cluster")
class TestSparkTableConstraintsDdlEnforcement(
    BaseSparkConstraintsDdlEnforcementSetup, BaseConstraintsRuntimeDdlEnforcement
):
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "my_model.sql": my_model_wrong_order_sql,
            "constraints_schema.yml": constraints_yml,
        }


@pytest.mark.skip_profile("databricks_cluster")
class TestSparkIncrementalConstraintsDdlEnforcement(
    BaseSparkConstraintsDdlEnforcementSetup,
    BaseIncrementalConstraintsRuntimeDdlEnforcement,
):
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "my_model.sql": my_model_incremental_wrong_order_sql,
            "constraints_schema.yml": constraints_yml,
        }


class BaseSparkConstraintsRollbackSetup:
    @pytest.fixture(scope="class")
    def project_config_update(self):
        return {
            "models": {
                "+file_format": "delta",
            }
        }

    @pytest.fixture(scope="class")
    def expected_error_messages(self):
        return [
            "violate the new CHECK constraint",
            "DELTA_NEW_CHECK_CONSTRAINT_VIOLATION",
            "violate the new NOT NULL constraint",
            "(id > 0) violated by row with values:",  # incremental mats
            "DELTA_VIOLATE_CONSTRAINT_WITH_VALUES",  # incremental mats
        ]

    def assert_expected_error_messages(self, error_message, expected_error_messages):
        # This needs to be ANY instead of ALL
        # The CHECK constraint is added before the NOT NULL constraint
        # and different connection types display/truncate the error message in different ways...
        assert any(msg in error_message for msg in expected_error_messages)


@pytest.mark.skip_profile("databricks_cluster")
class TestSparkTableConstraintsRollback(BaseSparkConstraintsRollbackSetup, BaseConstraintsRollback):
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "my_model.sql": my_model_sql,
            "constraints_schema.yml": constraints_yml,
        }

    # On Spark/Databricks, constraints are applied *after* the table is replaced.
    # We don't have any way to "rollback" the table to its previous happy state.
    # So the 'color' column will be updated to 'red', instead of 'blue'.
    @pytest.fixture(scope="class")
    def expected_color(self):
        return "red"


@pytest.mark.skip_profile("databricks_cluster")
class TestSparkIncrementalConstraintsRollback(
    BaseSparkConstraintsRollbackSetup, BaseIncrementalConstraintsRollback
):
    # color stays blue for incremental models since it's a new row that just
    # doesn't get inserted
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "my_model.sql": my_incremental_model_sql,
            "constraints_schema.yml": constraints_yml,
        }


incremental_foreign_key_schema_yml = """
version: 2

models:
  - name: raw_numbers
    config:
      contract:
        enforced: true
      materialized: table
    columns:
        - name: n
          data_type: integer
          constraints:
            - type: primary_key
            - type: not_null
  - name: stg_numbers
    config:
      contract:
        enforced: true
      materialized: incremental
      on_schema_change: append_new_columns
      unique_key: n
    columns:
      - name: n
        data_type: integer
        constraints:
          - type: foreign_key
            name: fk_n
            expression: (n) REFERENCES {schema}.raw_numbers
"""


@pytest.mark.skip_profile("databricks_cluster")
class TestDatabricksIncrementalForeignKeyConstraint:
    @pytest.fixture(scope="class")
    def models(self):
        return {
            "schema.yml": incremental_foreign_key_schema_yml,
            "raw_numbers.sql": incremental_foreign_key_model_raw_numbers_sql,
            "stg_numbers.sql": incremental_foreign_key_model_stg_numbers_sql,
        }

    def test_incremental_foreign_key_constraint(self, project):
        unformatted_constraint_schema_yml = read_file("models", "schema.yml")
        write_file(
            unformatted_constraint_schema_yml.format(schema=project.test_schema),
            "models",
            "schema.yml",
        )

        run_dbt(["run", "--select", "raw_numbers"])
        run_dbt(["run", "--select", "stg_numbers"])
        run_dbt(["run", "--select", "stg_numbers"])
