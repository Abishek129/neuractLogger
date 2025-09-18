"""
Simple PLC Data Logger Application

This script implements a command???line application for configuring and running
data logging tasks against programmable logic controllers (PLCs) using a
generic architecture based on the requirements provided by the user.  The
application does not talk to real PLCs over Modbus or OPC??UA; instead it
uses simulated connectors that generate synthetic values.  The goal is
to demonstrate the entire workflow ??? from defining parent schemas and
device tables to mapping columns and starting both continuous and
trigger???based logging jobs.

The core concepts implemented here are:

  * **Parent schemas** (categories) describe the set of columns for a
    family of devices.  For example `LTPanel` might have columns
    `r_current`, `y_current`, `avg_current` and `voltage`.
  * **Device tables** represent specific pieces of equipment (e.g.
    `Transformer_1`, `HTTransformer_3` or `Inverter_7`).  Each table
    inherits all of the columns from its parent schema and stores
    logged data into its own physical table inside a SQLite database.
    A `timestamp_utc` column is automatically added to every table.
  * **Mappings** link each column in a device table to a simulated
    Modbus register or OPC??UA node.  The mapping also stores metadata
    such as data type, scaling factor, deadband and polling period.
  * **Logging jobs** define how and when data should be recorded.  A
    job may run at a fixed interval (continuous logging) or only log
    when one or more trigger conditions are met (trigger???based
    logging).

The code uses Python's built???in `sqlite3` module for data storage and
`threading` for asynchronous polling.  Because the environment cannot
install external packages or talk to real PLCs, all device reads are
simulated.  You can extend the `SimulatedDeviceConnection` class to
connect to actual PLCs when running on a machine with appropriate
libraries.

Running the application
=======================

From a terminal in this repository, run:

```
python3 -m plc_logger.main
```

Follow the prompts to create schemas, devices, mappings and logging
jobs.  The program writes logged rows into a SQLite file you specify
when creating each device.  Use a separate terminal to examine the
created tables with the `sqlite3` command if desired.

This implementation is intentionally minimalist in order to run within
the constraints of the offline environment.  In a production
deployment you would likely replace the CLI with a graphical
front???end (e.g. React/Tauri) and swap the simulated connector for
real Modbus/OPC??UA drivers.  Nevertheless the structure presented
here should serve as a blueprint for further development.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

################################################################################
# Data model classes
################################################################################


@dataclass
class Field:
    """Represents a single column in a parent schema.

    Attributes:
        name: Name of the column.
        dtype: Logical data type (e.g. 'float', 'int', 'bool', 'str').
        unit: Optional engineering unit (e.g. 'A', 'V', '??C').
        scale: Multiplicative scaling factor applied to raw values.
    """

    name: str
    dtype: str
    unit: str = ""
    scale: float = 1.0


@dataclass
class ParentSchema:
    """Defines a family of devices with shared columns.

    Attributes:
        name: The schema/category name (e.g. 'LTPanel').
        fields: List of Field objects describing the columns.
    """

    name: str
    fields: List[Field] = field(default_factory=list)

    def add_field(self, field: Field) -> None:
        """Add a new field to the schema.

        Args:
            field: Field instance to append.
        """
        # Ensure unique field names within the schema
        if any(f.name == field.name for f in self.fields):
            raise ValueError(f"Field '{field.name}' already exists in schema '{self.name}'.")
        self.fields.append(field)

    def get_field_names(self) -> List[str]:
        return [f.name for f in self.fields]


@dataclass
class Mapping:
    """Associates a device field with a simulated register/node.

    Attributes:
        field_name: Name of the device column being mapped.
        protocol: 'modbus' or 'opc_ua'.  Used for demonstration only.
        address: The Modbus register or OPC??UA node identifier.
        data_type: Logical data type expected ('float', 'int', 'bool', 'str').
        scale: Multiplier applied to raw values read from the connector.
        deadband: Minimum change required to log an update (for change triggers).
        poll_ms: Polling period for continuous logging (milliseconds).  When
                 None, the job's global interval is used.
    """

    field_name: str
    protocol: str
    address: str
    data_type: str
    scale: float = 1.0
    deadband: float = 0.0
    poll_ms: Optional[int] = None


@dataclass
class DeviceTable:
    """Represents a physical table for logging a specific device.

    Attributes:
        name: Unique name of the device/table (e.g. 'Transformer_1').
        schema_name: Name of the parent schema this device is derived from.
        db_path: Path to the SQLite database file where data is stored.
        mappings: A mapping from field names to Mapping objects.
    """

    name: str
    schema_name: str
    db_path: str
    mappings: Dict[str, Mapping] = field(default_factory=dict)

    def get_table_name(self) -> str:
        """Returns the SQL table name.  We normalise to lower case and
        underscore separators so that it works in most SQL dialects.
        """
        return self.name.lower().replace(" ", "_")


@dataclass
class Trigger:
    """Represents a trigger condition for trigger???based logging.

    Attributes:
        field_name: Column to watch.
        op: Comparison operator or 'change'.  Supported ops: 'change', '>',
            '>=', '<', '<=', '==', '!='.
        value: Threshold value used for comparison ops (ignored for 'change').
        deadband: Minimum change for the 'change' operator.
    """

    field_name: str
    op: str
    value: Optional[float] = None
    deadband: float = 0.0


class LoggingJob:
    """A job that periodically polls a device and writes rows to the database.

    The job runs in a background thread.  Continuous jobs collect values on
    every tick based on the configured interval.  Trigger jobs only write
    a row when at least one trigger condition is satisfied.
    """

    def __init__(
        self,
        device: DeviceTable,
        parent_schema: ParentSchema,
        job_type: str = "continuous",
        interval_ms: int = 1000,
        triggers: Optional[List[Trigger]] = None,
    ) -> None:
        if job_type not in ("continuous", "trigger"):
            raise ValueError("job_type must be 'continuous' or 'trigger'")
        self.device = device
        self.parent_schema = parent_schema
        self.job_type = job_type
        self.interval_ms = interval_ms
        self.triggers = triggers or []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # Maintain last logged values for change detection
        self._last_values: Dict[str, Any] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            print(f"Job on {self.device.name} is already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"Started {self.job_type} job on {self.device.name} (interval {self.interval_ms} ms).")

    def stop(self) -> None:
        if not self._thread:
            print(f"Job on {self.device.name} is not running.")
            return
        self._stop_event.set()
        self._thread.join()
        self._thread = None
        print(f"Stopped job on {self.device.name}.")

    def _run(self) -> None:
        # Create table if not exists
        self._ensure_table()
        # Acquire a simulated connection for the device
        conn = SimulatedDeviceConnection(self.device)
        # Determine column names
        column_names = [f.name for f in self.parent_schema.fields]
        # Build insert statement
        placeholders = ", ".join(["?" for _ in column_names])
        insert_sql = (
            f"INSERT INTO {self.device.get_table_name()} "
            f"(timestamp_utc, {', '.join(column_names)}) "
            f"VALUES (?, {placeholders})"
        )

        while not self._stop_event.is_set():
            # Determine values for each field (based on per???field poll periods if provided)
            now = int(time.time())
            values: Dict[str, Any] = {}
            for field in self.parent_schema.fields:
                mapping = self.device.mappings.get(field.name)
                if mapping is None:
                    # Unmapped fields get None
                    values[field.name] = None
                    continue
                # For continuous jobs we ignore per???field poll rates and always read
                # For trigger jobs we may need to read anyway to evaluate triggers
                raw_value = conn.read(mapping)
                # Apply scaling
                try:
                    scaled = float(raw_value) * mapping.scale if raw_value is not None else None
                except Exception:
                    scaled = None
                values[field.name] = scaled

            # Determine whether to write
            should_log = False
            if self.job_type == "continuous":
                should_log = True
            else:
                # Trigger job: check conditions
                for trig in self.triggers:
                    val = values.get(trig.field_name)
                    prev = self._last_values.get(trig.field_name)
                    if val is None:
                        continue
                    if trig.op == "change":
                        if prev is None or abs(val - prev) > max(trig.deadband, 0.0):
                            should_log = True
                            break
                    elif trig.op in (">", ">=", "<", "<=", "==", "!="):
                        # Only support numeric comparisons for simplicity
                        if prev is None:
                            # Evaluate against threshold only
                            if self._evaluate(val, trig.op, trig.value):
                                should_log = True
                                break
                        else:
                            if self._evaluate(val, trig.op, trig.value):
                                should_log = True
                                break
                    else:
                        print(f"Unsupported trigger operator: {trig.op}")
                # Save last values for change detection
            if should_log:
                # Update last values for change detection
                for f, v in values.items():
                    self._last_values[f] = v
                self._write_row(insert_sql, now, [values[c] for c in column_names])
            # Sleep until next interval
            time.sleep(self.interval_ms / 1000.0)

    def _evaluate(self, val: float, op: str, threshold: Optional[float]) -> bool:
        if threshold is None:
            return False
        if op == ">":
            return val > threshold
        elif op == ">=":
            return val >= threshold
        elif op == "<":
            return val < threshold
        elif op == "<=":
            return val <= threshold
        elif op == "==":
            return val == threshold
        elif op == "!=":
            return val != threshold
        return False

    def _ensure_table(self) -> None:
        """Creates the logging table if it does not already exist."""
        db_path = self.device.db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with sqlite3.connect(db_path) as db:
            cols = [f"{f.name} REAL" for f in self.parent_schema.fields]
            cols_sql = ", ".join(cols)
            table_name = self.device.get_table_name()
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} "
                f"(timestamp_utc INTEGER, {cols_sql})"
            )
            db.commit()

    def _write_row(self, insert_sql: str, timestamp: int, values: List[Any]) -> None:
        db_path = self.device.db_path
        with sqlite3.connect(db_path) as db:
            db.execute(insert_sql, (timestamp, *values))
            db.commit()


################################################################################
# Simulated device connection
################################################################################


class SimulatedDeviceConnection:
    """Simulates reading values from a device.

    A real implementation would talk to Modbus or OPC??UA.  Here we
    generate pseudo???random values that drift slowly over time.  Each
    address has an independent value.
    """

    def __init__(self, device: DeviceTable) -> None:
        self.device = device
        # Store state per address to generate repeatable sequences
        self._state: Dict[str, float] = {}

    def read(self, mapping: Mapping) -> Any:
        """Return a simulated value for the given mapping."""
        addr = f"{mapping.protocol}:{mapping.address}"
        if mapping.data_type == "bool":
            # Flip boolean with small probability
            current = self._state.get(addr, 0.0)
            if random.random() < 0.05:
                current = 1.0 - current
            self._state[addr] = current
            return bool(current)
        elif mapping.data_type in ("int", "float"):
            current = self._state.get(addr, random.random() * 100.0)
            # Random walk
            delta = random.uniform(-1.0, 1.0)
            current += delta
            self._state[addr] = current
            return int(current) if mapping.data_type == "int" else float(current)
        elif mapping.data_type == "str":
            # Return a random string from a fixed list
            choices = ["OK", "WARN", "ALARM"]
            if addr not in self._state or random.random() < 0.1:
                self._state[addr] = random.choice(choices)
            return str(self._state[addr])
        else:
            return None


################################################################################
# CLI application
################################################################################


class LoggerApp:
    """Entry point for the interactive command???line application."""

    def __init__(self) -> None:
        # Keep definitions of parent schemas and devices in memory
        self.schemas: Dict[str, ParentSchema] = {}
        self.devices: Dict[str, DeviceTable] = {}
        self.jobs: List[LoggingJob] = []

    # ---------------------------------------------------------------------
    # Schema management
    # ---------------------------------------------------------------------

    def create_schema(self) -> None:
        name = input("Enter parent schema name: ").strip()
        if not name:
            print("Schema name cannot be empty.")
            return
        if name in self.schemas:
            print(f"Schema '{name}' already exists.")
            return
        schema = ParentSchema(name)
        print("Define fields for this schema. Enter empty name to finish.")
        while True:
            fname = input("  Field name (leave blank when done): ").strip()
            if not fname:
                break
            dtype = input("    Data type (float/int/bool/str): ").strip().lower()
            if dtype not in ("float", "int", "bool", "str"):
                print("    Invalid type. Choose from float, int, bool, str.")
                continue
            unit = input("    Unit (optional): ").strip()
            try:
                scale_str = input("    Scale (default 1.0): ").strip()
                scale = float(scale_str) if scale_str else 1.0
            except ValueError:
                print("    Invalid scale. Using 1.0.")
                scale = 1.0
            try:
                schema.add_field(Field(fname, dtype, unit, scale))
            except ValueError as e:
                print(f"    {e}")
                continue
        if not schema.fields:
            print("No fields defined. Schema not created.")
            return
        self.schemas[name] = schema
        print(f"Schema '{name}' created with fields: {', '.join(schema.get_field_names())}")

    def list_schemas(self) -> None:
        if not self.schemas:
            print("No schemas defined.")
            return
        for name, schema in self.schemas.items():
            field_names = ", ".join(f.name for f in schema.fields)
            print(f"- {name}: {field_names}")

    # ---------------------------------------------------------------------
    # Device management
    # ---------------------------------------------------------------------

    def create_device(self) -> None:
        if not self.schemas:
            print("Define at least one schema before creating devices.")
            return
        name = input("Enter device/table name: ").strip()
        if not name:
            print("Device name cannot be empty.")
            return
        if name in self.devices:
            print(f"Device '{name}' already exists.")
            return
        # Choose a schema
        print("Available schemas:")
        for i, s in enumerate(self.schemas.keys(), 1):
            print(f"  {i}) {s}")
        try:
            choice = int(input("Select schema (number): ").strip())
        except ValueError:
            print("Invalid selection.")
            return
        schema_names = list(self.schemas.keys())
        if choice < 1 or choice > len(schema_names):
            print("Selection out of range.")
            return
        schema_name = schema_names[choice - 1]
        db_path = input(
            "Path to SQLite DB file for this device (will be created if missing): "
        ).strip()
        if not db_path:
            print("DB path cannot be empty.")
            return
        # Create device and initialise mapping dict
        device = DeviceTable(name=name, schema_name=schema_name, db_path=db_path)
        # Initialise mapping entries to None
        for field in self.schemas[schema_name].fields:
            device.mappings[field.name] = None
        self.devices[name] = device
        print(f"Device '{name}' created with schema '{schema_name}'.")

    def list_devices(self) -> None:
        if not self.devices:
            print("No devices defined.")
            return
        for name, dev in self.devices.items():
            print(f"- {name}: schema={dev.schema_name}, DB={dev.db_path}")

    # ---------------------------------------------------------------------
    # Mapping management
    # ---------------------------------------------------------------------

    def configure_mapping(self) -> None:
        if not self.devices:
            print("Define at least one device before mapping.")
            return
        # Select device
        dev_names = list(self.devices.keys())
        print("Available devices:")
        for i, n in enumerate(dev_names, 1):
            print(f"  {i}) {n}")
        try:
            choice = int(input("Select device (number): ").strip())
        except ValueError:
            print("Invalid selection.")
            return
        if choice < 1 or choice > len(dev_names):
            print("Selection out of range.")
            return
        device = self.devices[dev_names[choice - 1]]
        schema = self.schemas[device.schema_name]
        print(f"Configuring mapping for device '{device.name}' (schema {schema.name})")
        for field in schema.fields:
            print(f"Field: {field.name} (type {field.dtype})")
            protocol = input("  Protocol (modbus/opc_ua) [leave blank to skip]: ").strip().lower()
            if not protocol:
                # leave mapping unchanged
                continue
            if protocol not in ("modbus", "opc_ua"):
                print("    Unsupported protocol. Skipping.")
                continue
            address = input("    Address/NodeId: ").strip()
            if not address:
                print("    Address cannot be empty. Skipping.")
                continue
            # Use field dtype as default mapping dtype
            dtype = field.dtype
            data_type = input(f"    Data type [{dtype}]: ").strip().lower() or dtype
            if data_type not in ("float", "int", "bool", "str"):
                print("    Invalid data type. Skipping.")
                continue
            # Scaling
            try:
                scale_str = input("    Scale (default 1.0): ").strip()
                scale = float(scale_str) if scale_str else 1.0
            except ValueError:
                print("    Invalid scale. Using 1.0.")
                scale = 1.0
            # Deadband
            try:
                db_str = input("    Deadband (default 0.0): ").strip()
                deadband = float(db_str) if db_str else 0.0
            except ValueError:
                print("    Invalid deadband. Using 0.0.")
                deadband = 0.0
            # Poll ms (optional)
            try:
                poll_str = input("    Poll ms (leave blank to use job interval): ").strip()
                poll_ms = int(poll_str) if poll_str else None
            except ValueError:
                print("    Invalid poll ms. Ignoring per???field poll period.")
                poll_ms = None
            device.mappings[field.name] = Mapping(
                field_name=field.name,
                protocol=protocol,
                address=address,
                data_type=data_type,
                scale=scale,
                deadband=deadband,
                poll_ms=poll_ms,
            )
        print(f"Mapping updated for device '{device.name}'.")

    def show_mapping(self) -> None:
        if not self.devices:
            print("No devices defined.")
            return
        for name, device in self.devices.items():
            print(f"Device '{name}':")
            for field_name, mapping in device.mappings.items():
                if mapping is None:
                    print(f"  {field_name}: [unmapped]")
                else:
                    print(
                        f"  {field_name}: protocol={mapping.protocol}, address={mapping.address}, "
                        f"dtype={mapping.data_type}, scale={mapping.scale}, deadband={mapping.deadband}, poll={mapping.poll_ms}"
                    )

    # ---------------------------------------------------------------------
    # Logging job management
    # ---------------------------------------------------------------------

    def create_job(self) -> None:
        if not self.devices:
            print("Define at least one device before creating a job.")
            return
        # Choose device
        dev_names = list(self.devices.keys())
        print("Available devices:")
        for i, n in enumerate(dev_names, 1):
            print(f"  {i}) {n}")
        try:
            choice = int(input("Select device (number): ").strip())
        except ValueError:
            print("Invalid selection.")
            return
        if choice < 1 or choice > len(dev_names):
            print("Selection out of range.")
            return
        device = self.devices[dev_names[choice - 1]]
        schema = self.schemas[device.schema_name]
        # Choose job type
        job_type = input("Job type (continuous/trigger) [continuous]: ").strip().lower() or "continuous"
        if job_type not in ("continuous", "trigger"):
            print("Unsupported job type.")
            return
        # Job interval
        try:
            interval_str = input("Interval ms (default 1000): ").strip()
            interval_ms = int(interval_str) if interval_str else 1000
        except ValueError:
            print("Invalid interval. Using 1000 ms.")
            interval_ms = 1000
        triggers: List[Trigger] = []
        if job_type == "trigger":
            print(
                "Define trigger conditions. One per line. Supported ops: change, >, >=, <, <=, ==, !=. "
                "Leave field blank to finish."
            )
            while True:
                field_name = input("  Field name (blank to finish): ").strip()
                if not field_name:
                    break
                if field_name not in [f.name for f in schema.fields]:
                    print(f"    Field '{field_name}' does not exist. Skipping.")
                    continue
                op = input("    Operator (change/>/>=/</<=/==/!=): ").strip()
                if op not in ("change", ">", ">=", "<", "<=", "==", "!="):
                    print("    Unsupported operator. Skipping.")
                    continue
                value = None
                deadband = 0.0
                if op == "change":
                    try:
                        db_str = input("    Deadband for change (default 0.0): ").strip()
                        deadband = float(db_str) if db_str else 0.0
                    except ValueError:
                        print("    Invalid deadband. Using 0.0.")
                        deadband = 0.0
                else:
                    try:
                        val_str = input("    Threshold value: ").strip()
                        value = float(val_str)
                    except ValueError:
                        print("    Invalid threshold. Skipping.")
                        continue
                triggers.append(Trigger(field_name=field_name, op=op, value=value, deadband=deadband))
        # Instantiate and start job
        job = LoggingJob(device, schema, job_type, interval_ms, triggers)
        self.jobs.append(job)
        job.start()
        print(f"Job created and started for device '{device.name}'.")

    def list_jobs(self) -> None:
        if not self.jobs:
            print("No jobs running.")
            return
        for i, job in enumerate(self.jobs, 1):
            device_name = job.device.name
            status = "running" if job._thread and job._thread.is_alive() else "stopped"
            print(f"  {i}) Device: {device_name}, type: {job.job_type}, interval: {job.interval_ms} ms, status: {status}")

    def stop_job(self) -> None:
        if not self.jobs:
            print("No jobs defined.")
            return
        # List jobs
        for i, job in enumerate(self.jobs, 1):
            device_name = job.device.name
            status = "running" if job._thread and job._thread.is_alive() else "stopped"
            print(f"  {i}) Device: {device_name}, type: {job.job_type}, status: {status}")
        try:
            choice = int(input("Select job to stop (number): ").strip())
        except ValueError:
            print("Invalid selection.")
            return
        if choice < 1 or choice > len(self.jobs):
            print("Selection out of range.")
            return
        job = self.jobs[choice - 1]
        job.stop()
        # Remove from list
        self.jobs.pop(choice - 1)

    # ---------------------------------------------------------------------
    # Main loop
    # ---------------------------------------------------------------------

    def run(self) -> None:
        """Enter the main command loop."""
        print("Welcome to the Neuract Logger CLI\n")
        actions = {
            "1": ("Create parent schema", self.create_schema),
            "2": ("List schemas", self.list_schemas),
            "3": ("Create device/table", self.create_device),
            "4": ("List devices", self.list_devices),
            "5": ("Configure mapping", self.configure_mapping),
            "6": ("Show mappings", self.show_mapping),
            "7": ("Create logging job", self.create_job),
            "8": ("List jobs", self.list_jobs),
            "9": ("Stop job", self.stop_job),
            "0": ("Exit", None),
        }
        while True:
            print("\nChoose an action:")
            for key, (label, _) in actions.items():
                print(f"  {key}) {label}")
            choice = input("> ").strip()
            if choice == "0":
                # Stop all jobs before exiting
                for job in self.jobs[:]:
                    job.stop()
                print("Exiting. Goodbye!")
                break
            action = actions.get(choice)
            if not action:
                print("Invalid choice. Try again.")
                continue
            # Execute selected action
            func = action[1]
            if func:
                try:
                    func()
                except Exception as e:
                    print(f"Error: {e}")


def main() -> None:
    app = LoggerApp()
    app.run()


if __name__ == "__main__":
    main()
