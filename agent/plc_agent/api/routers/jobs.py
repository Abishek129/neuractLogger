from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel

from ..store import Store

from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, UniqueConstraint, inspect, insert, select, update

from opcua import Client, ua

import threading, time, uuid

from typing import Optional, Callable, Union

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.interval import IntervalTrigger

DATABASE_URL = "sqlite:///mydatabase.db" 

jobstores = {
    'default': SQLAlchemyJobStore(url=DATABASE_URL)
}

scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()

router = APIRouter()

class JobThread(threading.Thread):
    def __init__(self, job_id: int, name: str, interval: float):
        super().__init__()
        self.job_id = job_id
        self.name = name
        self.interval = interval
        self.state = "running"
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def run(self):
        while not self._stop_event.is_set():
            with self._lock:
                if self.state == "paused":
                    time.sleep(0.5)
                    continue
            print(f"[{self.name}] Running job (id={self.job_id})...")
            # client = Client("opc.tcp://localhost:4840/freeopcua/server/")
            # client.connect()

            # try:
            #     for i in range(1, 11):
            #         nodeid = f"ns=2;s=Device{i}.Temperature"
            #         node = client.get_node(nodeid)
            #         value = node.get_value()
            #         print(f"Device{i} Temperature: {value}")
            # finally:
            #     client.disconnect()
            time.sleep(self.interval)
        print(f"[{self.name}] Stopped.")

    def pause(self):
        with self._lock:
            self.state = "paused"

    def resume(self):
        with self._lock:
            self.state = "running"

    def stop(self):
        self._stop_event.set()

job_threads: Dict[int, JobThread] = {}

def opcua_job(job_id: int,**kwargs):
    client = Client("opc.tcp://localhost:4840/freeopcua/server/")
    table = kwargs.get("table", "default_table")
    engine = create_engine(DATABASE_URL)
    metadata = MetaData()
    try:
        client.connect()
        #with engine.connect() as conn:
        for i in range(1, 11):
            node_id_str = f"ns=2;s=Device{i}.Temperature"
            node = client.get_node(node_id_str)
            try:
                value = node.get_value()
            except Exception as e:
                print(f"[Job {job_id}] Error reading {node_id_str}: {e}")
                value = None
            print(f"[Job {job_id}] {node_id_str} = {value}")
                # ins = insert(table).values(
                #     job_id=job_id,
                #     node_id=node_id_str,
                #     value=float(value) if value is not None else None,
                #     timestamp=datetime.utcnow(),
                # )
                #conn.execute(ins)
            #conn.commit()
        print(f"[Job {job_id}] Readings logged.")
    finally:
        client.disconnect()


class Job(BaseModel):
    name: str
    type: str = "continuous"
    status: str = "stopped"
    table: str
    intervalMs: int = 1000

class JobCreate(BaseModel):
    name: str
    interval_seconds: int
    type: str = "continuous"
    table: str
    args: Optional[List[Any]] = []
    kwargs: Optional[Dict[str, Any]] = {}


@router.get("/jobs")
def list_jobs() -> List[Dict[str, Any]]:
    # engine = create_engine(DATABASE_URL)
    # metadata = MetaData()
    # metadata.reflect(bind=engine)
    # jobs_table = metadata.tables["jobs"]

    # with engine.connect() as conn:
    #     result = conn.execute(select(jobs_table))
    #     jobs = result.mappings().all()
    # return jobs
    jobs = scheduler.get_jobs()
    result = []
    for job in jobs:
        result.append({
            "id": job.id,
            "name": job.kwargs.get("name", ""),
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
            "type": job.kwargs.get("type", ""),
            "table": job.kwargs.get("table", ""),
            "paused": job.next_run_time is None
        })
    return result


@router.post("/jobs", status_code=201)
def create_job(job : JobCreate):
    # try:
    #     payload = payload.dict()

    #     engine = create_engine(DATABASE_URL)
    #     metadata = MetaData()

    #     # Define the jobs table
    #     jobs_table = Table(
    #         "jobs",
    #         metadata,
    #         Column("id", Integer, primary_key=True, nullable=False, autoincrement=True),
    #         Column("name", String, nullable=False),
    #         Column("type", String, nullable=False, default="continuous"),
    #         Column("status", String, nullable=False, default="stopped"),
    #         Column("table", String, nullable=False),
    #         Column("intervalMs", Integer, nullable=False, default=1000),
    #     )

    #     metadata.create_all(bind=engine)

    #     with engine.connect() as conn:
    #         job = insert(jobs_table).values(
    #             name=payload.get("name"),
    #             type=payload.get("type", "continuous"),
    #             status=payload.get("status", "stopped"),
    #             table=payload.get("table"),
    #             intervalMs=payload.get("intervalMs", 1000)
    #         )
    #         conn.execute(job)
    #         conn.commit()
    #         print("Job Created.")

    #     return {"ok": True, "job": payload}

    # except ValueError as e:
    #     raise HTTPException(status_code=400, detail=str(e))
    job_id = str(uuid.uuid4())

    for existing_job in scheduler.get_jobs():
        if existing_job.kwargs.get("table") == job.table:
            raise HTTPException(status_code=400, detail=f"Job with table '{job.table}' already exists")

    trigger = IntervalTrigger(seconds=job.interval_seconds)

    job_kwargs = job.kwargs.copy()
    job_kwargs.update({
        "name": job.name,
        "type": job.type,
        "table": job.table
    })

    scheduler.add_job(
        opcua_job,
        trigger=trigger,
        id=job_id,
        args=[job_id],
        kwargs=job_kwargs
    )
    return {"message": f"Job '{job.name}' created", "job_id": job_id}


@router.post("/jobs/{job_id}/start")
def start_job(job_id) -> Dict[str, Any]:
    pass
    # try:
    #     job_id = int(job_id)
    #     engine = create_engine(DATABASE_URL)
    #     metadata = MetaData()
    #     metadata.reflect(bind=engine)
    #     jobs_table = metadata.tables["jobs"]

    #     job = None

    #     with engine.connect() as conn:
    #         stmt = select(jobs_table).where(jobs_table.c.id == job_id)
    #         result = conn.execute(stmt)
    #         job = result.mappings().all()
    #         print("Starting job:", job)
    #         if not job:
    #             raise HTTPException(status_code=404, detail="Job not found")

    #         job = job[0]

    #         if job.status in ["running", "paused"]:
    #             return {"message": f"Job already {job.status}"}

    #     thread = JobThread(job_id, job.name, job.intervalMs/1000.0)
    #     thread.start()
    #     job_threads[job_id] = thread

    #     with engine.connect() as conn:
    #         update_stmt = jobs_table.update().where(jobs_table.c.id == job_id).values(status="running")
    #         conn.execute(update_stmt)
    #         conn.commit()
        
    #     return {"message": f"Job {job.name} started"}
    # except ValueError:
    #     raise HTTPException(status_code=400, detail="Invalid job ID")
    ##################################################
    # job_id_str = f"job_{job_id}"
    
    # if scheduler.get_job(job_id_str):
    #     scheduler.remove_job(job_id_str)
    # scheduler.add_job(
    #     opcua_job,
    #     IntervalTrigger(seconds=interval_seconds),
    #     id=job_id_str,
    #     args=[job_id, interval_seconds],
    #     replace_existing=True,
    # )
    # return {"message": f"Job {job_id} started with interval {interval_seconds} seconds"}



@router.post("/jobs/{job_id}/stop")
def stop_job(job_id: str):
    job_id = int(job_id)
    engine = create_engine(DATABASE_URL)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    jobs_table = metadata.tables["jobs"]

    job = None

    with engine.connect() as conn:
        stmt = select(jobs_table).where(jobs_table.c.id == job_id)
        result = conn.execute(stmt)
        job = result.mappings().all()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        job = job[0]
        if job.status == "stopped":
            raise HTTPException(status_code=400, detail="Job not running")

    job_threads[job_id].stop()
    with engine.connect() as conn:
        update_stmt = jobs_table.update().where(jobs_table.c.id == job_id).values(status="stopped")
        conn.execute(update_stmt)
        conn.commit()
    return {"message": f"Job {job.name} stopped"}

@router.post("/jobs/{job_id}/pause")
def pause_job(job_id: str):
    # job_id = int(job_id)
    # engine = create_engine(DATABASE_URL)
    # metadata = MetaData()
    # metadata.reflect(bind=engine)
    # jobs_table = metadata.tables["jobs"]

    # job = None

    # with engine.connect() as conn:
    #     stmt = select(jobs_table).where(jobs_table.c.id == job_id)
    #     result = conn.execute(stmt)
    #     job = result.mappings().all()
    #     if not job:
    #         raise HTTPException(status_code=404, detail="Job not found")
    #     job = job[0]
    #     if job.status != "running":
    #         raise HTTPException(status_code=400, detail="Job not running")

    # job_threads[job_id].pause()
    # with engine.connect() as conn:
    #     update_stmt = jobs_table.update().where(jobs_table.c.id == job_id).values(status="paused")
    #     conn.execute(update_stmt)
    #     conn.commit()
    # return {"message": f"Job {job.name} paused"}
    job = scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    scheduler.pause_job(job_id)
    return {"message": f"Job '{job_id}' paused"}

@router.post("/jobs/{job_id}/resume")
def resume_job(job_id: str):
    # job_id = int(job_id)
    # engine = create_engine(DATABASE_URL)
    # metadata = MetaData()
    # metadata.reflect(bind=engine)
    # jobs_table = metadata.tables["jobs"]

    # job = None

    # with engine.connect() as conn:
    #     stmt = select(jobs_table).where(jobs_table.c.id == job_id)
    #     result = conn.execute(stmt)
    #     job = result.mappings().all()
    #     if not job:
    #         raise HTTPException(status_code=404, detail="Job not found")
    #     job = job[0]
    #     if job.status != "paused":
    #         raise HTTPException(status_code=400, detail="Job not paused")

    # job_threads[job_id].resume()
    # with engine.connect() as conn:
    #     update_stmt = jobs_table.update().where(jobs_table.c.id == job_id).values(status="running")
    #     conn.execute(update_stmt)
    #     conn.commit()
    # return {"message": f"Job {job.name} resumed"}
    job = scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    scheduler.resume_job(job_id)
    return {"message": f"Job '{job_id}' resumed"}

@router.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    # job_id = int(job_id)
    # engine = create_engine(DATABASE_URL)
    # metadata = MetaData()
    # metadata.reflect(bind=engine)
    # jobs_table = metadata.tables["jobs"]

    # job = None

    # with engine.connect() as conn:
    #     stmt = select(jobs_table).where(jobs_table.c.id == job_id)
    #     result = conn.execute(stmt)
    #     job = result.mappings().all()
    #     if not job:
    #         raise HTTPException(status_code=404, detail="Job not found")
    #     job = job[0]

    # if job_id in job_threads:
    #     job_threads[job_id].stop()
    #     del job_threads[job_id]

    # with engine.connect() as conn:
    #     delete_stmt = jobs_table.delete().where(jobs_table.c.id == job_id)
    #     conn.execute(delete_stmt)
    #     conn.commit()
    
    # return {"message": f"Job {job.name} deleted"}
    job = scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    scheduler.remove_job(job_id)
    return {"message": f"Job '{job_id}' deleted"}


# @router.post("/jobs/{job_id}/dry_run")
# def dry_run_job(job_id: str) -> Dict[str, Any]:
#     job = Store.instance().get_job(job_id)
#     if not job:
#         raise HTTPException(status_code=404, detail="not_found")
#     # Stub metrics
#     return {"ok": True, "job": job_id, "duration_s": 60, "metrics": {"readRate": 0, "writeRate": 0}}


# @router.post("/jobs/{job_id}/backfill")
# def backfill_job(job_id: str) -> Dict[str, Any]:
#     job = Store.instance().get_job(job_id)
#     if not job:
#         raise HTTPException(status_code=404, detail="not_found")
#     return {"ok": True, "job": job_id, "snapshot": True}






# from fastapi import FastAPI, HTTPException
# from opcua import Client
# from typing import Dict
# import threading
# import time

# app = FastAPI(title="OPC UA Job Manager")

# OPC_SERVER_URL = "opc.tcp://localhost:4840/freeopcua/server/"
# client = Client(OPC_SERVER_URL)
# client.connect()

# # ----------- Job Definition -----------

# class MonitoringJob(threading.Thread):
#     def __init__(self, name: str, nodeid: str, interval: float = 2.0):
#         super().__init__()
#         self.name = name
#         self.nodeid = nodeid
#         self.interval = interval
#         self.state = "running"  # can be "paused", "running", "stopped"
#         self._lock = threading.Lock()
#         self._stop_event = threading.Event()

#     def run(self):
#         node = client.get_node(self.nodeid)
#         print(f"🚀 Job {self.name} started (monitoring {self.nodeid})")
#         while not self._stop_event.is_set():
#             with self._lock:
#                 if self.state == "paused":
#                     time.sleep(0.5)
#                     continue
#             try:
#                 value = node.get_value()
#                 print(f"[{self.name}] {self.nodeid} = {value}")
#             except Exception as e:
#                 print(f"[{self.name}] Read error: {e}")
#             time.sleep(self.interval)
#         print(f"🛑 Job {self.name} has stopped.")

#     def pause(self):
#         with self._lock:
#             self.state = "paused"

#     def resume(self):
#         with self._lock:
#             self.state = "running"

#     def stop(self):
#         self._stop_event.set()
#         with self._lock:
#             self.state = "stopped"

#     def get_state(self):
#         with self._lock:
#             return self.state


# # ----------- Job Manager -----------

# jobs: Dict[str, MonitoringJob] = {}


# # ----------- API Endpoints -----------

# @app.get("/jobs")
# def list_jobs():
#     return {
#         name: {
#             "nodeid": job.nodeid,
#             "interval": job.interval,
#             "status": job.get_state()
#         } for name, job in jobs.items()
#     }

# @app.post("/jobs/start")
# def start_job(name: str, nodeid: str, interval: float = 2.0):
#     if name in jobs:
#         raise HTTPException(status_code=400, detail="Job name already exists")
#     job = MonitoringJob(name=name, nodeid=nodeid, interval=interval)
#     job.start()
#     jobs[name] = job
#     return {"message": f"Job '{name}' started", "nodeid": nodeid}

# @app.post("/jobs/{name}/pause")
# def pause_job(name: str):
#     job = jobs.get(name)
#     if not job:
#         raise HTTPException(status_code=404, detail="Job not found")
#     job.pause()
#     return {"message": f"Job '{name}' paused"}

# @app.post("/jobs/{name}/resume")
# def resume_job(name: str):
#     job = jobs.get(name)
#     if not job:
#         raise HTTPException(status_code=404, detail="Job not found")
#     job.resume()
#     return {"message": f"Job '{name}' resumed"}

# @app.delete("/jobs/{name}")
# def stop_job(name: str):
#     job = jobs.pop(name, None)
#     if not job:
#         raise HTTPException(status_code=404, detail="Job not found")
#     job.stop()
#     return {"message": f"Job '{name}' stopped and removed"}


