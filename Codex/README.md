# PLC Logger

> Refer to index.md in this folder for a quick list of the other documents.

This project contains a command‑line application for configuring and
running a programmable logic controller (PLC) data logger.  It was
created to satisfy a set of requirements for a Windows desktop
application that would:

* Allow an operator to define **parent schemas** (categories) for
  devices such as `LTPanel`, `HTPanel` and `Inverter`.
* Create **device tables** (for example `Transformer_1`, `HTTransformer_3` or
  `Inverter_7`) that inherit the columns from a parent schema.
* Map each column of every device table to a register or node in a
  Modbus or OPC UA server.
* Run **continuous** or **trigger‑based** logging jobs that poll
  devices at a fixed interval or only write when a condition is met.
* Write logged values into per‑device tables in an SQL database.

Because the environment in which this code was written does not allow
the installation of external packages or real PLC communication
libraries, the implementation is intentionally minimalist:

* The only database backend supported out of the box is **SQLite**.
  You can specify any file path for the database when you create a
  device; it will be created automatically if it does not exist.
* A **simulated connector** generates pseudo‑random values for each
  address/node.  It emulates boolean flips, numeric random walks and
  status strings to provide realistic‑looking data during logging.
* The user interface is a **command‑line menu**.  A React/Tauri
  desktop UI could be developed later by building upon the core
  classes in `plc_logger/main.py`.

## Usage

1. Open a terminal and navigate to the root of this repository.
2. Run the application with:

   ```bash
   python3 -m plc_logger.main
   ```

3. Use the menu to:
   * Create parent schemas and define their fields.
   * Create device tables based on those schemas, specifying a
     SQLite database file for storing logged data.
   * Configure the mapping of each column to a simulated Modbus
     register or OPC UA node.
   * Start continuous or trigger‑based logging jobs.
   * List or stop running jobs.

4. Open the SQLite database with a tool like `sqlite3` to inspect
   the logged data.  Each device will have its own table named after
   the device (converted to lower case and underscores).

## Extending to Real PLCs

The `SimulatedDeviceConnection` class in `plc_logger/main.py` is where
values are generated.  To connect to actual PLCs:

1. Replace or extend `SimulatedDeviceConnection` with a class that
   uses a Modbus library (e.g. `pymodbus`) or OPC UA library (e.g.
   `opcua`), mapping the `protocol` and `address` properties of
   `Mapping` objects to appropriate read operations.
2. Ensure that your environment has network access and the required
   dependencies installed.
3. You may also adapt the database layer to use other SQL engines
   (MySQL, PostgreSQL, TimescaleDB, etc.) by replacing calls to
   `sqlite3` with the relevant client libraries.  Alternatively you
   can log to generic SQL via SQLAlchemy or another ORM.

## Limitations

* There is no concurrency control on configuration changes – avoid
  modifying mappings while jobs are running.
* Trigger‑based jobs support only simple comparisons or change
  detection.  Complex logical expressions could be implemented by
  extending the trigger parser.
* Only a command‑line interface is provided.  A GUI was beyond the
  scope of what could be delivered in the offline environment but can
  be developed later using these classes.

## License

This code is provided for demonstration purposes and has no
particular licence.  Feel free to adapt and use it in your projects.