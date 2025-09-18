# Build Log

## Step 1 - Environment Check

### Command: python --version
```
Python 3.13.3
```

### Command: pyinstaller --version
```
6.15.0
```

### Command: pip show pyinstaller
```
Name: pyinstaller
Version: 6.15.0
Summary: PyInstaller bundles a Python application and all its dependencies into a single package.
Home-page: https://www.pyinstaller.org/
Author: Hartmut Goebel, Giovanni Bajo, David Vierra, David Cortesi, Martin Zibricky
Author-email: 
License: GPLv2-or-later with a special exception which allows to use PyInstaller to build and distribute non-free programs (including commercial ones)
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: altgraph, packaging, pefile, pyinstaller-hooks-contrib, pywin32-ctypes, setuptools
Required-by: 
```

### Command: pip show pyinstaller-hooks-contrib
```
Name: pyinstaller-hooks-contrib
Version: 2025.8
Summary: Community maintained hooks for PyInstaller
Home-page: https://github.com/pyinstaller/pyinstaller-hooks-contrib
Author: 
Author-email: 
License: 
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: packaging, setuptools
Required-by: pyinstaller
```

### Command: pip show fastapi
```
Name: fastapi
Version: 0.116.1
Summary: FastAPI framework, high performance, easy to learn, fast to code, ready for production
Home-page: https://github.com/fastapi/fastapi
Author: 
Author-email: =?utf-8?q?Sebasti=C3=A1n_Ram=C3=ADrez?= <tiangolo@gmail.com>
License: 
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: pydantic, starlette, typing-extensions
Required-by: 
```

### Command: pip show uvicorn
```
Name: uvicorn
Version: 0.35.0
Summary: The lightning-fast ASGI server.
Home-page: https://www.uvicorn.org/
Author: 
Author-email: Tom Christie <tom@tomchristie.com>, Marcelo Trylesinski <marcelotryle@gmail.com>
License-Expression: BSD-3-Clause
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: click, h11
Required-by: 
```

### Command: pip show sqlmodel
```
Name: sqlmodel
Version: 0.0.24
Summary: SQLModel, SQL databases in Python, designed for simplicity, compatibility, and robustness.
Home-page: https://github.com/fastapi/sqlmodel
Author: 
Author-email: =?utf-8?q?Sebasti=C3=A1n_Ram=C3=ADrez?= <tiangolo@gmail.com>
License: 
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: pydantic, SQLAlchemy
Required-by: 
```

### Command: pip show sqlalchemy
```
Name: SQLAlchemy
Version: 2.0.43
Summary: Database Abstraction Library
Home-page: https://www.sqlalchemy.org
Author: Mike Bayer
Author-email: mike_mp@zzzcomputing.com
License: MIT
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: greenlet, typing-extensions
Required-by: sqlmodel
```

### Command: pip show psutil
```
Name: psutil
Version: 7.0.0
Summary: Cross-platform lib for process and system monitoring in Python.  NOTE: the syntax of this script MUST be kept compatible with Python 2.7.
Home-page: https://github.com/giampaolo/psutil
Author: Giampaolo Rodola
Author-email: g.rodola@gmail.com
License: BSD-3-Clause
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: 
Required-by: 
```

### Command: pip show apscheduler
```
Name: APScheduler
Version: 3.11.0
Summary: In-process task scheduler with Cron-like capabilities
Home-page: 
Author: 
Author-email: Alex Gr÷nholm <alex.gronholm@nextday.fi>
License: MIT
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: tzlocal
Required-by: 
```

### Command: pip show pymodbus
```
Name: pymodbus
Version: 3.11.2
Summary: A fully featured modbus protocol stack in python
Home-page: https://github.com/pymodbus-dev/pymodbus/
Author: Galen Collins, Jan Iversen
Author-email: 
License: BSD-3-Clause
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: 
Required-by: 
```

### Command: pip show opcua
```
Name: opcua
Version: 0.98.13
Summary: Pure Python OPC-UA client and server library
Home-page: http://freeopcua.github.io/
Author: Olivier Roulet-Dubonnet
Author-email: olivier.roulet@gmail.com
License: GNU Lesser General Public License v3 or later
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: lxml, python-dateutil, pytz
Required-by: 
```

### Command: pip show icmplib
```
Name: icmplib
Version: 3.0.4
Summary: Easily forge ICMP packets and make your own ping and traceroute.
Home-page: https://github.com/ValentinBELYN/icmplib
Author: Valentin BELYN
Author-email: valentin-hello@gmx.com
License: GNU Lesser General Public License v3.0
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: 
Required-by: 
```

### Command: pip show cryptography
```
Name: cryptography
Version: 45.0.7
Summary: cryptography is a package which provides cryptographic recipes and primitives to Python developers.
Home-page: https://github.com/pyca/cryptography
Author: The cryptography developers <cryptography-dev@python.org>
Author-email: The Python Cryptographic Authority and individual contributors <cryptography-dev@python.org>
License: Apache-2.0 OR BSD-3-Clause
Location: C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages
Requires: cffi
Required-by: 
```

## Step 2 - Backend Build`r`n
### Command: Remove-Item dist\plc-agent-core -Recurse -Force -ErrorAction SilentlyContinue
```
(no output)
```

### Command: Remove-Item build\plc-agent-core -Recurse -Force -ErrorAction SilentlyContinue
```
(no output)
```

### Command: pyinstaller --noconfirm --clean plc-agent-core.spec
```
command timed out after ~47s; rerunning with extended timeout.
```

### Retry Command: pyinstaller --noconfirm --clean plc-agent-core.spec
```
97 INFO: PyInstaller: 6.15.0, contrib hooks: 2025.8
97 INFO: Python: 3.13.3
112 INFO: Platform: Windows-11-10.0.26100-SP0
112 INFO: Python environment: C:\Users\pc\AppData\Local\Programs\Python\Python313
113 INFO: Removing temporary files and cleaning cache in C:\Users\pc\AppData\Local\pyinstaller
117 INFO: Module search paths (PYTHONPATH):
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\pyinstaller.exe',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\python313.zip',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\DLLs',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32\\lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\Pythonwin',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\setuptools\\_vendor',
 'D:\\Apps\\plc_logger_app\\plc_logger\\agent']
292 INFO: checking Analysis
292 INFO: Building Analysis because Analysis-00.toc is non existent
292 INFO: Running Analysis Analysis-00.toc
292 INFO: Target bytecode optimization level: 0
292 INFO: Initializing module dependency graph...
292 INFO: Initializing module graph hook caches...
299 INFO: Analyzing modules for base_library.zip ...
959 INFO: Processing standard module hook 'hook-encodings.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2108 INFO: Processing standard module hook 'hook-pickle.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2589 INFO: Processing standard module hook 'hook-heapq.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2849 INFO: Caching module dependency graph...
2869 INFO: Looking for Python shared library...
2872 INFO: Using Python shared library: C:\Users\pc\AppData\Local\Programs\Python\Python313\python313.dll
2872 INFO: Analyzing D:\Apps\plc_logger_app\plc_logger\agent\run_agent.py
3046 INFO: Processing standard module hook 'hook-sqlite3.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3254 INFO: Processing standard module hook 'hook-_ctypes.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3401 INFO: Processing standard module hook 'hook-multiprocessing.util.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3461 INFO: Processing standard module hook 'hook-xml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3902 INFO: Processing standard module hook 'hook-pydantic.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\pydantic\experimental\__init__.py:7: PydanticExperimentalWarning: This module is experimental, its contents are subject to change and deprecation.
  warnings.warn(
4132 INFO: Processing pre-safe-import-module hook 'hook-typing_extensions.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
4133 INFO: SetuptoolsInfo: initializing cached setuptools info...
6170 INFO: Processing standard module hook 'hook-platform.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6402 INFO: Processing standard module hook 'hook-zoneinfo.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
6414 INFO: Processing standard module hook 'hook-sysconfig.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6937 INFO: Processing standard module hook 'hook-anyio.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
7765 INFO: Processing standard module hook 'hook-sqlalchemy.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8068 INFO: Processing pre-safe-import-module hook 'hook-importlib_metadata.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8068 INFO: Setuptools: 'importlib_metadata' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.importlib_metadata'!
8072 INFO: Processing standard module hook 'hook-setuptools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8083 INFO: Processing pre-safe-import-module hook 'hook-distutils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8100 INFO: Processing pre-safe-import-module hook 'hook-jaraco.functools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8100 INFO: Setuptools: 'jaraco.functools' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.jaraco.functools'!
8108 INFO: Processing pre-safe-import-module hook 'hook-more_itertools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8108 INFO: Setuptools: 'more_itertools' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.more_itertools'!
8224 INFO: Processing pre-safe-import-module hook 'hook-packaging.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8345 INFO: Processing pre-safe-import-module hook 'hook-jaraco.text.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8345 INFO: Setuptools: 'jaraco.text' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.jaraco.text'!
8359 INFO: Processing standard module hook 'hook-setuptools._vendor.jaraco.text.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8360 INFO: Processing pre-safe-import-module hook 'hook-importlib_resources.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8360 INFO: Processing pre-safe-import-module hook 'hook-jaraco.context.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8361 INFO: Setuptools: 'jaraco.context' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.jaraco.context'!
8470 INFO: Processing pre-safe-import-module hook 'hook-backports.tarfile.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8471 INFO: Setuptools: 'backports.tarfile' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.backports.tarfile'!
8521 INFO: Processing standard module hook 'hook-backports.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
8697 INFO: Processing pre-safe-import-module hook 'hook-tomli.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8697 INFO: Setuptools: 'tomli' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.tomli'!
8983 INFO: Processing pre-safe-import-module hook 'hook-wheel.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8983 INFO: Setuptools: 'wheel' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.wheel'!
9088 INFO: Processing standard module hook 'hook-setuptools._vendor.importlib_metadata.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9089 INFO: Processing pre-safe-import-module hook 'hook-zipp.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
9090 INFO: Setuptools: 'zipp' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.zipp'!
10962 INFO: Processing standard module hook 'hook-uvicorn.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
11634 INFO: Processing standard module hook 'hook-difflib.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11932 INFO: Processing standard module hook 'hook-websockets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
12417 INFO: Processing standard module hook 'hook-psutil.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
14239 INFO: Processing standard module hook 'hook-pytz.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14582 INFO: Processing standard module hook 'hook-dateutil.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
14666 INFO: Processing pre-safe-import-module hook 'hook-six.moves.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
14923 INFO: Processing standard module hook 'hook-xml.etree.cElementTree.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14973 INFO: Processing standard module hook 'hook-cryptography.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
15458 INFO: hook-cryptography: cryptography does not seem to be using dynamically linked OpenSSL.
15641 INFO: Processing standard module hook 'hook-lxml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
15830 INFO: Processing standard module hook 'hook-lxml.objectify.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
15943 INFO: Processing standard module hook 'hook-shelve.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
18977 INFO: Processing standard module hook 'hook-apscheduler.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
19180 INFO: Processing module hooks (post-graph stage)...
19389 INFO: Processing standard module hook 'hook-lxml.etree.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
19525 INFO: Processing standard module hook 'hook-lxml.isoschematron.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
19928 INFO: Processing standard module hook 'hook-sqlalchemy.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
20135 WARNING: Hidden import "pysqlite2" not found!
20135 WARNING: Hidden import "MySQLdb" not found!
20136 WARNING: Hidden import "psycopg2" not found!
20650 INFO: Processing standard module hook 'hook-tzdata.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
20905 INFO: Performing binary vs. data reclassification (1257 entries)
20943 INFO: Looking for ctypes DLLs
20970 INFO: Analyzing run-time hooks ...
20974 INFO: Including run-time hook 'pyi_rth_inspect.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
20976 INFO: Including run-time hook 'pyi_rth_pkgutil.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
20977 INFO: Including run-time hook 'pyi_rth_multiprocessing.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
20978 INFO: Including run-time hook 'pyi_rth_cryptography_openssl.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\rthooks'
20978 INFO: Including run-time hook 'pyi_rth_setuptools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
21001 INFO: Creating base_library.zip...
21027 INFO: Looking for dynamic libraries
C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\pydantic\experimental\__init__.py:7: PydanticExperimentalWarning: This module is experimental, its contents are subject to change and deprecation.
  warnings.warn(
21801 INFO: Extra DLL search directories (AddDllDirectory): []
21801 INFO: Extra DLL search directories (PATH): []
22060 INFO: Warnings written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\warn-plc-agent-core.txt
22115 INFO: Graph cross-reference written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\xref-plc-agent-core.html
22149 INFO: checking PYZ
22149 INFO: Building PYZ because PYZ-00.toc is non existent
22149 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\PYZ-00.pyz
23157 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\PYZ-00.pyz completed successfully.
23173 INFO: checking PKG
23173 INFO: Building PKG because PKG-00.toc is non existent
23173 INFO: Building PKG (CArchive) plc-agent-core.pkg
23194 INFO: Building PKG (CArchive) plc-agent-core.pkg completed successfully.
23194 INFO: Bootloader C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\bootloader\Windows-64bit-intel\runw.exe
23194 INFO: checking EXE
23194 INFO: Building EXE because EXE-00.toc is non existent
23194 INFO: Building EXE from EXE-00.toc
23194 INFO: Copying bootloader EXE to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\plc-agent-core.exe
23198 INFO: Copying icon to EXE
23200 INFO: Copying 0 resources to EXE
23200 INFO: Embedding manifest in EXE
23203 INFO: Appending PKG archive to EXE
23248 INFO: Fixing EXE headers
24986 INFO: Building EXE from EXE-00.toc completed successfully.
24994 INFO: checking COLLECT
24994 INFO: Building COLLECT because COLLECT-00.toc is non existent
24994 INFO: Removing dir D:\Apps\plc_logger_app\plc_logger\dist\plc-agent-core
25051 INFO: Building COLLECT COLLECT-00.toc
26259 INFO: Building COLLECT COLLECT-00.toc completed successfully.
26271 INFO: Build complete! The results are available in: D:\Apps\plc_logger_app\plc_logger\dist
```

### Command: Remove-Item dist\plc-agent-core -Recurse -Force -ErrorAction SilentlyContinue (post-fix rebuild)
```
(no output)
```

### Command: Remove-Item build\plc-agent-core -Recurse -Force -ErrorAction SilentlyContinue (post-fix rebuild)
```
(no output)
```

### Command: pyinstaller --noconfirm --clean plc-agent-core.spec (post-fix rebuild)
```
95 INFO: PyInstaller: 6.15.0, contrib hooks: 2025.8
95 INFO: Python: 3.13.3
109 INFO: Platform: Windows-11-10.0.26100-SP0
109 INFO: Python environment: C:\Users\pc\AppData\Local\Programs\Python\Python313
111 INFO: Removing temporary files and cleaning cache in C:\Users\pc\AppData\Local\pyinstaller
111 INFO: Module search paths (PYTHONPATH):
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\pyinstaller.exe',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\python313.zip',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\DLLs',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32\\lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\Pythonwin',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\setuptools\\_vendor',
 'D:\\Apps\\plc_logger_app\\plc_logger\\agent']
296 INFO: checking Analysis
296 INFO: Building Analysis because Analysis-00.toc is non existent
296 INFO: Running Analysis Analysis-00.toc
296 INFO: Target bytecode optimization level: 0
296 INFO: Initializing module dependency graph...
297 INFO: Initializing module graph hook caches...
303 INFO: Analyzing modules for base_library.zip ...
949 INFO: Processing standard module hook 'hook-heapq.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
1009 INFO: Processing standard module hook 'hook-encodings.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2227 INFO: Processing standard module hook 'hook-pickle.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2924 INFO: Caching module dependency graph...
2944 INFO: Looking for Python shared library...
2947 INFO: Using Python shared library: C:\Users\pc\AppData\Local\Programs\Python\Python313\python313.dll
2947 INFO: Analyzing D:\Apps\plc_logger_app\plc_logger\agent\run_agent.py
2955 INFO: Processing module hooks (post-graph stage)...
2957 INFO: Performing binary vs. data reclassification (1 entries)
2958 INFO: Looking for ctypes DLLs
2960 INFO: Analyzing run-time hooks ...
2961 INFO: Including run-time hook 'pyi_rth_inspect.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
2963 INFO: Creating base_library.zip...
2988 INFO: Looking for dynamic libraries
3045 INFO: Extra DLL search directories (AddDllDirectory): []
3045 INFO: Extra DLL search directories (PATH): []
3152 INFO: Warnings written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\warn-plc-agent-core.txt
3158 INFO: Graph cross-reference written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\xref-plc-agent-core.html
3167 INFO: checking PYZ
3167 INFO: Building PYZ because PYZ-00.toc is non existent
3167 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\PYZ-00.pyz
3303 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\PYZ-00.pyz completed successfully.
3308 INFO: checking PKG
3309 INFO: Building PKG because PKG-00.toc is non existent
3309 INFO: Building PKG (CArchive) plc-agent-core.pkg
3323 INFO: Building PKG (CArchive) plc-agent-core.pkg completed successfully.
3323 INFO: Bootloader C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\bootloader\Windows-64bit-intel\runw.exe
3323 INFO: checking EXE
3323 INFO: Building EXE because EXE-00.toc is non existent
3323 INFO: Building EXE from EXE-00.toc
3323 INFO: Copying bootloader EXE to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\plc-agent-core.exe
3326 INFO: Copying icon to EXE
3328 INFO: Copying 0 resources to EXE
3328 INFO: Embedding manifest in EXE
3331 INFO: Appending PKG archive to EXE
3377 INFO: Fixing EXE headers
3620 INFO: Building EXE from EXE-00.toc completed successfully.
3621 INFO: checking COLLECT
3621 INFO: Building COLLECT because COLLECT-00.toc is non existent
3621 INFO: Building COLLECT COLLECT-00.toc
3762 INFO: Building COLLECT COLLECT-00.toc completed successfully.
3763 INFO: Build complete! The results are available in: D:\Apps\plc_logger_app\plc_logger\dist
```

### Command: Get-Process plc-agent-core -ErrorAction SilentlyContinue | Stop-Process -Force
```
process stopped
```

### Command: Remove-Item dist\plc-agent-core -Recurse -Force -ErrorAction SilentlyContinue (rebuild)
```
(no output)
```

### Command: Remove-Item build\plc-agent-core -Recurse -Force -ErrorAction SilentlyContinue (rebuild)
```
(no output)
```

### Command: pyinstaller --noconfirm --clean plc-agent-core.spec (final rebuild)
```
100 INFO: PyInstaller: 6.15.0, contrib hooks: 2025.8
100 INFO: Python: 3.13.3
115 INFO: Platform: Windows-11-10.0.26100-SP0
115 INFO: Python environment: C:\Users\pc\AppData\Local\Programs\Python\Python313
116 INFO: Removing temporary files and cleaning cache in C:\Users\pc\AppData\Local\pyinstaller
117 INFO: Module search paths (PYTHONPATH):
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\pyinstaller.exe',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\python313.zip',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\DLLs',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32\\lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\Pythonwin',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\setuptools\\_vendor',
 'D:\\Apps\\plc_logger_app\\plc_logger\\agent']
294 INFO: checking Analysis
294 INFO: Building Analysis because Analysis-00.toc is non existent
294 INFO: Running Analysis Analysis-00.toc
294 INFO: Target bytecode optimization level: 0
294 INFO: Initializing module dependency graph...
295 INFO: Initializing module graph hook caches...
301 INFO: Analyzing modules for base_library.zip ...
839 INFO: Processing standard module hook 'hook-heapq.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
864 INFO: Processing standard module hook 'hook-encodings.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2137 INFO: Processing standard module hook 'hook-pickle.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2905 INFO: Caching module dependency graph...
2923 INFO: Looking for Python shared library...
2926 INFO: Using Python shared library: C:\Users\pc\AppData\Local\Programs\Python\Python313\python313.dll
2926 INFO: Analyzing D:\Apps\plc_logger_app\plc_logger\agent\run_agent.py
3099 INFO: Processing standard module hook 'hook-sqlite3.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3298 INFO: Processing standard module hook 'hook-_ctypes.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3445 INFO: Processing standard module hook 'hook-multiprocessing.util.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3504 INFO: Processing standard module hook 'hook-xml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3936 INFO: Processing standard module hook 'hook-pydantic.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\pydantic\experimental\__init__.py:7: PydanticExperimentalWarning: This module is experimental, its contents are subject to change and deprecation.
  warnings.warn(
4151 INFO: Processing pre-safe-import-module hook 'hook-typing_extensions.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
4152 INFO: SetuptoolsInfo: initializing cached setuptools info...
6174 INFO: Processing standard module hook 'hook-platform.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6403 INFO: Processing standard module hook 'hook-zoneinfo.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
6415 INFO: Processing standard module hook 'hook-sysconfig.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6934 INFO: Processing standard module hook 'hook-anyio.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
7774 INFO: Processing standard module hook 'hook-sqlalchemy.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8087 INFO: Processing pre-safe-import-module hook 'hook-importlib_metadata.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8087 INFO: Setuptools: 'importlib_metadata' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.importlib_metadata'!
8091 INFO: Processing standard module hook 'hook-setuptools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8102 INFO: Processing pre-safe-import-module hook 'hook-distutils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8120 INFO: Processing pre-safe-import-module hook 'hook-jaraco.functools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8121 INFO: Setuptools: 'jaraco.functools' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.jaraco.functools'!
8128 INFO: Processing pre-safe-import-module hook 'hook-more_itertools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8128 INFO: Setuptools: 'more_itertools' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.more_itertools'!
8241 INFO: Processing pre-safe-import-module hook 'hook-packaging.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8360 INFO: Processing pre-safe-import-module hook 'hook-jaraco.text.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8360 INFO: Setuptools: 'jaraco.text' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.jaraco.text'!
8373 INFO: Processing standard module hook 'hook-setuptools._vendor.jaraco.text.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8374 INFO: Processing pre-safe-import-module hook 'hook-importlib_resources.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8375 INFO: Processing pre-safe-import-module hook 'hook-jaraco.context.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8375 INFO: Setuptools: 'jaraco.context' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.jaraco.context'!
8485 INFO: Processing pre-safe-import-module hook 'hook-backports.tarfile.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8486 INFO: Setuptools: 'backports.tarfile' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.backports.tarfile'!
8534 INFO: Processing standard module hook 'hook-backports.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
8710 INFO: Processing pre-safe-import-module hook 'hook-tomli.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8711 INFO: Setuptools: 'tomli' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.tomli'!
8994 INFO: Setuptools: 'wheel' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.wheel'!
9098 INFO: Processing standard module hook 'hook-setuptools._vendor.importlib_metadata.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9099 INFO: Processing pre-safe-import-module hook 'hook-zipp.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
9099 INFO: Setuptools: 'zipp' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.zipp'!
10941 INFO: Processing standard module hook 'hook-uvicorn.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
11604 INFO: Processing standard module hook 'hook-difflib.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11897 INFO: Processing standard module hook 'hook-websockets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
12367 INFO: Processing standard module hook 'hook-psutil.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
14165 INFO: Processing standard module hook 'hook-pytz.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14501 INFO: Processing standard module hook 'hook-dateutil.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
14581 INFO: Processing pre-safe-import-module hook 'hook-six.moves.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
14834 INFO: Processing standard module hook 'hook-xml.etree.cElementTree.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14883 INFO: Processing standard module hook 'hook-cryptography.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
15379 INFO: hook-cryptography: cryptography does not seem to be using dynamically linked OpenSSL.
15562 INFO: Processing standard module hook 'hook-lxml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
15766 INFO: Processing standard module hook 'hook-lxml.objectify.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
15881 INFO: Processing standard module hook 'hook-shelve.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
18869 INFO: Processing standard module hook 'hook-apscheduler.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
19080 INFO: Processing module hooks (post-graph stage)...
19291 INFO: Processing standard module hook 'hook-lxml.etree.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
19425 INFO: Processing standard module hook 'hook-lxml.isoschematron.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
19827 INFO: Processing standard module hook 'hook-sqlalchemy.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
20048 WARNING: Hidden import "pysqlite2" not found!
20048 WARNING: Hidden import "MySQLdb" not found!
20048 WARNING: Hidden import "psycopg2" not found!
20568 INFO: Processing standard module hook 'hook-tzdata.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
20831 INFO: Performing binary vs. data reclassification (1257 entries)
20878 INFO: Looking for ctypes DLLs
20906 INFO: Analyzing run-time hooks ...
20909 INFO: Including run-time hook 'pyi_rth_inspect.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
20911 INFO: Including run-time hook 'pyi_rth_pkgutil.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
20912 INFO: Including run-time hook 'pyi_rth_multiprocessing.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
20914 INFO: Including run-time hook 'pyi_rth_cryptography_openssl.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\rthooks'
20914 INFO: Including run-time hook 'pyi_rth_setuptools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
20936 INFO: Creating base_library.zip...
20962 INFO: Looking for dynamic libraries
C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\pydantic\experimental\__init__.py:7: PydanticExperimentalWarning: This module is experimental, its contents are subject to change and deprecation.
  warnings.warn(
21735 INFO: Extra DLL search directories (AddDllDirectory): []
21735 INFO: Extra DLL search directories (PATH): []
21994 INFO: Warnings written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\warn-plc-agent-core.txt
22051 INFO: Graph cross-reference written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\xref-plc-agent-core.html
22084 INFO: checking PYZ
22084 INFO: Building PYZ because PYZ-00.toc is non existent
22084 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\PYZ-00.pyz
23087 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\PYZ-00.pyz completed successfully.
23103 INFO: checking PKG
23103 INFO: Building PKG because PKG-00.toc is non existent
23103 INFO: Building PKG (CArchive) plc-agent-core.pkg
23126 INFO: Building PKG (CArchive) plc-agent-core.pkg completed successfully.
23127 INFO: Bootloader C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\bootloader\Windows-64bit-intel\runw.exe
23127 INFO: checking EXE
23127 INFO: Building EXE because EXE-00.toc is non existent
23127 INFO: Building EXE from EXE-00.toc
23127 INFO: Copying bootloader EXE to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\plc-agent-core.exe
23131 INFO: Copying icon to EXE
23133 INFO: Copying 0 resources to EXE
23133 INFO: Embedding manifest in EXE
23136 INFO: Appending PKG archive to EXE
23201 INFO: Fixing EXE headers
23963 INFO: Building EXE from EXE-00.toc completed successfully.
23972 INFO: checking COLLECT
23972 INFO: Building COLLECT because COLLECT-00.toc is non existent
23972 INFO: Building COLLECT COLLECT-00.toc
24733 INFO: Building COLLECT COLLECT-00.toc completed successfully.
24746 INFO: Build complete! The results are available in: D:\Apps\plc_logger_app\plc_logger\dist
```

### Command: pyinstaller --noconfirm --clean plc-agent-core.spec (final rebuild)
```
pyinstaller.exe : 95 INFO: PyInstaller: 6.15.0, contrib hooks: 2025.8
At line:1 char:8
+ $out = & pyinstaller --noconfirm --clean plc-agent-core.spec 2>&1; $o ...
+        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (95 INFO: PyInst...b hooks: 2025.8:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 
95 INFO: Python: 3.13.3
109 INFO: Platform: Windows-11-10.0.26100-SP0
109 INFO: Python environment: C:\Users\pc\AppData\Local\Programs\Python\Python313
110 INFO: Removing temporary files and cleaning cache in C:\Users\pc\AppData\Local\pyinstaller
115 INFO: Module search paths (PYTHONPATH):
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\pyinstaller.exe',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\python313.zip',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\DLLs',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32\\lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\Pythonwin',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\setuptools\\_vendor',
 'D:\\Apps\\plc_logger_app\\plc_logger\\agent']
298 INFO: checking Analysis
298 INFO: Building Analysis because Analysis-00.toc is non existent
298 INFO: Running Analysis Analysis-00.toc
298 INFO: Target bytecode optimization level: 0
298 INFO: Initializing module dependency graph...
298 INFO: Initializing module graph hook caches...
304 INFO: Analyzing modules for base_library.zip ...
1019 INFO: Processing standard module hook 'hook-encodings.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
1400 INFO: Processing standard module hook 'hook-heapq.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2105 INFO: Processing standard module hook 'hook-pickle.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2818 INFO: Caching module dependency graph...
2838 INFO: Looking for Python shared library...
2841 INFO: Using Python shared library: C:\Users\pc\AppData\Local\Programs\Python\Python313\python313.dll
2841 INFO: Analyzing D:\Apps\plc_logger_app\plc_logger\agent\run_agent.py
3014 INFO: Processing standard module hook 'hook-sqlite3.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3209 INFO: Processing standard module hook 'hook-_ctypes.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3355 INFO: Processing standard module hook 'hook-multiprocessing.util.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3415 INFO: Processing standard module hook 'hook-xml.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3865 INFO: Processing standard module hook 'hook-pydantic.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\pydantic\experimental\__init__.py:7: 
PydanticExperimentalWarning: This module is experimental, its contents are subject to change and deprecation.
  warnings.warn(
4096 INFO: Processing pre-safe-import-module hook 'hook-typing_extensions.py' from 'C:\\Users\\pc\\AppData\\Local\\Prog
rams\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
4097 INFO: SetuptoolsInfo: initializing cached setuptools info...
6144 INFO: Processing standard module hook 'hook-platform.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6374 INFO: Processing standard module hook 'hook-zoneinfo.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
6386 INFO: Processing standard module hook 'hook-sysconfig.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6902 INFO: Processing standard module hook 'hook-anyio.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
7719 INFO: Processing standard module hook 'hook-sqlalchemy.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8024 INFO: Processing pre-safe-import-module hook 'hook-importlib_metadata.py' from 'C:\\Users\\pc\\AppData\\Local\\Pro
grams\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8025 INFO: Setuptools: 'importlib_metadata' appears to be a setuptools-vendored copy - creating alias to 
'setuptools._vendor.importlib_metadata'!
8028 INFO: Processing standard module hook 'hook-setuptools.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8040 INFO: Processing pre-safe-import-module hook 'hook-distutils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Py
thon\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8056 INFO: Processing pre-safe-import-module hook 'hook-jaraco.functools.py' from 'C:\\Users\\pc\\AppData\\Local\\Progr
ams\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8056 INFO: Setuptools: 'jaraco.functools' appears to be a setuptools-vendored copy - creating alias to 
'setuptools._vendor.jaraco.functools'!
8063 INFO: Processing pre-safe-import-module hook 'hook-more_itertools.py' from 'C:\\Users\\pc\\AppData\\Local\\Program
s\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8064 INFO: Setuptools: 'more_itertools' appears to be a setuptools-vendored copy - creating alias to 
'setuptools._vendor.more_itertools'!
8177 INFO: Processing pre-safe-import-module hook 'hook-packaging.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Py
thon\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8295 INFO: Processing pre-safe-import-module hook 'hook-jaraco.text.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\
Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8296 INFO: Setuptools: 'jaraco.text' appears to be a setuptools-vendored copy - creating alias to 
'setuptools._vendor.jaraco.text'!
8308 INFO: Processing standard module hook 'hook-setuptools._vendor.jaraco.text.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8309 INFO: Processing pre-safe-import-module hook 'hook-importlib_resources.py' from 'C:\\Users\\pc\\AppData\\Local\\Pr
ograms\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8310 INFO: Processing pre-safe-import-module hook 'hook-jaraco.context.py' from 'C:\\Users\\pc\\AppData\\Local\\Program
s\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8310 INFO: Setuptools: 'jaraco.context' appears to be a setuptools-vendored copy - creating alias to 
'setuptools._vendor.jaraco.context'!
8418 INFO: Processing pre-safe-import-module hook 'hook-backports.tarfile.py' from 'C:\\Users\\pc\\AppData\\Local\\Prog
rams\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8419 INFO: Setuptools: 'backports.tarfile' appears to be a setuptools-vendored copy - creating alias to 
'setuptools._vendor.backports.tarfile'!
8468 INFO: Processing standard module hook 'hook-backports.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
8645 INFO: Processing pre-safe-import-module hook 'hook-tomli.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python
\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8645 INFO: Setuptools: 'tomli' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.tomli'!
8929 INFO: Processing pre-safe-import-module hook 'hook-wheel.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python
\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
8929 INFO: Setuptools: 'wheel' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.wheel'!
9032 INFO: Processing standard module hook 'hook-setuptools._vendor.importlib_metadata.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9033 INFO: Processing pre-safe-import-module hook 'hook-zipp.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\
\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
9033 INFO: Setuptools: 'zipp' appears to be a setuptools-vendored copy - creating alias to 'setuptools._vendor.zipp'!
10902 INFO: Processing standard module hook 'hook-uvicorn.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
11573 INFO: Processing standard module hook 'hook-difflib.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11873 INFO: Processing standard module hook 'hook-websockets.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
12339 INFO: Processing standard module hook 'hook-psutil.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
14129 INFO: Processing standard module hook 'hook-pytz.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14467 INFO: Processing standard module hook 'hook-dateutil.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
14548 INFO: Processing pre-safe-import-module hook 'hook-six.moves.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\P
ython\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
14802 INFO: Processing standard module hook 'hook-xml.etree.cElementTree.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14851 INFO: Processing standard module hook 'hook-cryptography.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
15342 INFO: hook-cryptography: cryptography does not seem to be using dynamically linked OpenSSL.
15523 INFO: Processing standard module hook 'hook-lxml.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
15724 INFO: Processing standard module hook 'hook-lxml.objectify.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
15837 INFO: Processing standard module hook 'hook-shelve.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
18825 INFO: Processing standard module hook 'hook-apscheduler.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
19036 INFO: Processing module hooks (post-graph stage)...
19243 INFO: Processing standard module hook 'hook-lxml.etree.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
19376 INFO: Processing standard module hook 'hook-lxml.isoschematron.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
19773 INFO: Processing standard module hook 'hook-sqlalchemy.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
19983 WARNING: Hidden import "pysqlite2" not found!
19984 WARNING: Hidden import "MySQLdb" not found!
19984 WARNING: Hidden import "psycopg2" not found!
20490 INFO: Processing standard module hook 'hook-tzdata.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
20737 INFO: Performing binary vs. data reclassification (1257 entries)
20777 INFO: Looking for ctypes DLLs
20804 INFO: Analyzing run-time hooks ...
20807 INFO: Including run-time hook 'pyi_rth_inspect.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
20809 INFO: Including run-time hook 'pyi_rth_pkgutil.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
20810 INFO: Including run-time hook 'pyi_rth_multiprocessing.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
20811 INFO: Including run-time hook 'pyi_rth_cryptography_openssl.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\rthooks'
20812 INFO: Including run-time hook 'pyi_rth_setuptools.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
20834 INFO: Creating base_library.zip...
20860 INFO: Looking for dynamic libraries
C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\pydantic\experimental\__init__.py:7: 
PydanticExperimentalWarning: This module is experimental, its contents are subject to change and deprecation.
  warnings.warn(
21610 INFO: Extra DLL search directories (AddDllDirectory): []
21610 INFO: Extra DLL search directories (PATH): []
21864 INFO: Warnings written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\warn-plc-agent-core.txt
21919 INFO: Graph cross-reference written to 
D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\xref-plc-agent-core.html
21952 INFO: checking PYZ
21953 INFO: Building PYZ because PYZ-00.toc is non existent
21953 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\PYZ-00.pyz
22974 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\PYZ-00.pyz completed 
successfully.
22991 INFO: checking PKG
22991 INFO: Building PKG because PKG-00.toc is non existent
22991 INFO: Building PKG (CArchive) plc-agent-core.pkg
23012 INFO: Building PKG (CArchive) plc-agent-core.pkg completed successfully.
23012 INFO: Bootloader C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\bootloader\Win
dows-64bit-intel\runw.exe
23012 INFO: checking EXE
23012 INFO: Building EXE because EXE-00.toc is non existent
23012 INFO: Building EXE from EXE-00.toc
23012 INFO: Copying bootloader EXE to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-core\plc-agent-core.exe
23015 INFO: Copying icon to EXE
23018 INFO: Copying 0 resources to EXE
23018 INFO: Embedding manifest in EXE
23020 INFO: Appending PKG archive to EXE
23079 INFO: Fixing EXE headers
23821 INFO: Building EXE from EXE-00.toc completed successfully.
23830 INFO: checking COLLECT
23830 INFO: Building COLLECT because COLLECT-00.toc is non existent
23830 INFO: Removing dir D:\Apps\plc_logger_app\plc_logger\dist\plc-agent-core
23888 INFO: Building COLLECT COLLECT-00.toc
24562 INFO: Building COLLECT COLLECT-00.toc completed successfully.
24575 INFO: Build complete! The results are available in: D:\Apps\plc_logger_app\plc_logger\dist
```

## Step 3 - Tray Build
### Command: Remove-Item dist\plc-agent-tray -Recurse -Force -ErrorAction SilentlyContinue
```
(no output)
```

### Command: Remove-Item build\plc-agent-tray -Recurse -Force -ErrorAction SilentlyContinue
```
(no output)
```

### Command: pyinstaller --noconfirm --clean plc-agent-tray.spec
```
pyinstaller.exe : 91 INFO: PyInstaller: 6.15.0, contrib hooks: 2025.8
At line:1 char:153
+ ... ``'; $out = & pyinstaller --noconfirm --clean plc-agent-tray.spec 2>& ...
+                 ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (91 INFO: PyInst...b hooks: 2025.8:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 
91 INFO: Python: 3.13.3
105 INFO: Platform: Windows-11-10.0.26100-SP0
105 INFO: Python environment: C:\Users\pc\AppData\Local\Programs\Python\Python313
106 INFO: Removing temporary files and cleaning cache in C:\Users\pc\AppData\Local\pyinstaller
140 INFO: Module search paths (PYTHONPATH):
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\pyinstaller.exe',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\python313.zip',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\DLLs',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32\\lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\Pythonwin',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\setuptools\\_vendor',
 'D:\\Apps\\plc_logger_app\\plc_logger\\apps']
304 INFO: checking Analysis
304 INFO: Building Analysis because Analysis-00.toc is non existent
304 INFO: Running Analysis Analysis-00.toc
304 INFO: Target bytecode optimization level: 0
304 INFO: Initializing module dependency graph...
304 INFO: Initializing module graph hook caches...
310 INFO: Analyzing modules for base_library.zip ...
1065 INFO: Processing standard module hook 'hook-encodings.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2020 INFO: Processing standard module hook 'hook-pickle.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2524 INFO: Processing standard module hook 'hook-heapq.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2737 INFO: Caching module dependency graph...
2754 INFO: Looking for Python shared library...
2757 INFO: Using Python shared library: C:\Users\pc\AppData\Local\Programs\Python\Python313\python313.dll
2757 INFO: Analyzing D:\Apps\plc_logger_app\plc_logger\apps\agent-tray\main.py
2877 INFO: Processing module hooks (post-graph stage)...
2879 INFO: Performing binary vs. data reclassification (1 entries)
2879 INFO: Looking for ctypes DLLs
2882 INFO: Analyzing run-time hooks ...
2882 INFO: Including run-time hook 'pyi_rth_inspect.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
2884 INFO: Creating base_library.zip...
2909 INFO: Looking for dynamic libraries
2961 INFO: Extra DLL search directories (AddDllDirectory): []
2961 INFO: Extra DLL search directories (PATH): []
3094 INFO: Warnings written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\warn-plc-agent-tray.txt
3101 INFO: Graph cross-reference written to 
D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\xref-plc-agent-tray.html
3110 INFO: checking PYZ
3110 INFO: Building PYZ because PYZ-00.toc is non existent
3110 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz
3253 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz completed 
successfully.
3260 INFO: checking PKG
3260 INFO: Building PKG because PKG-00.toc is non existent
3260 INFO: Building PKG (CArchive) plc-agent-tray.pkg
3286 INFO: Building PKG (CArchive) plc-agent-tray.pkg completed successfully.
3287 INFO: Bootloader C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\bootloader\Wind
ows-64bit-intel\runw.exe
3287 INFO: checking EXE
3287 INFO: Building EXE because EXE-00.toc is non existent
3287 INFO: Building EXE from EXE-00.toc
3287 INFO: Copying bootloader EXE to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\plc-agent-tray.exe
3291 INFO: Copying icon to EXE
3298 INFO: Copying 0 resources to EXE
3298 INFO: Embedding manifest in EXE
3332 INFO: Appending PKG archive to EXE
3363 INFO: Fixing EXE headers
3601 INFO: Building EXE from EXE-00.toc completed successfully.
3602 INFO: checking COLLECT
3602 INFO: Building COLLECT because COLLECT-00.toc is non existent
3602 INFO: Building COLLECT COLLECT-00.toc
3720 INFO: Building COLLECT COLLECT-00.toc completed successfully.
3720 INFO: Build complete! The results are available in: D:\Apps\plc_logger_app\plc_logger\dist
```

### Command: New-Item -ItemType Directory -Path dist\installer -Force
```
(created/confirmed)
```

### Command: makensis installers\nsis\plc-agent-tray.nsi
```
```

### Command: pip install -r apps/agent-tray/requirements.txt
```
Collecting PySide6>=6.7.0 (from -r apps/agent-tray/requirements.txt (line 1))
  Downloading pyside6-6.9.2-cp39-abi3-win_amd64.whl.metadata (5.5 kB)
Requirement already satisfied: pywin32>=306 in c:\users\pc\appdata\local\programs\python\python313\lib\site-packages (from -r apps/agent-tray/requirements.txt (line 2)) (311)
Collecting requests>=2.32.0 (from -r apps/agent-tray/requirements.txt (line 3))
  Using cached requests-2.32.5-py3-none-any.whl.metadata (4.9 kB)
Collecting shiboken6==6.9.2 (from PySide6>=6.7.0->-r apps/agent-tray/requirements.txt (line 1))
  Downloading shiboken6-6.9.2-cp39-abi3-win_amd64.whl.metadata (2.5 kB)
Collecting PySide6_Essentials==6.9.2 (from PySide6>=6.7.0->-r apps/agent-tray/requirements.txt (line 1))
  Downloading pyside6_essentials-6.9.2-cp39-abi3-win_amd64.whl.metadata (3.8 kB)
Collecting PySide6_Addons==6.9.2 (from PySide6>=6.7.0->-r apps/agent-tray/requirements.txt (line 1))
  Downloading pyside6_addons-6.9.2-cp39-abi3-win_amd64.whl.metadata (4.1 kB)
Collecting charset_normalizer<4,>=2 (from requests>=2.32.0->-r apps/agent-tray/requirements.txt (line 3))
  Using cached charset_normalizer-3.4.3-cp313-cp313-win_amd64.whl.metadata (37 kB)
Requirement already satisfied: idna<4,>=2.5 in c:\users\pc\appdata\local\programs\python\python313\lib\site-packages (from requests>=2.32.0->-r apps/agent-tray/requirements.txt (line 3)) (3.10)
Collecting urllib3<3,>=1.21.1 (from requests>=2.32.0->-r apps/agent-tray/requirements.txt (line 3))
  Using cached urllib3-2.5.0-py3-none-any.whl.metadata (6.5 kB)
Collecting certifi>=2017.4.17 (from requests>=2.32.0->-r apps/agent-tray/requirements.txt (line 3))
  Using cached certifi-2025.8.3-py3-none-any.whl.metadata (2.4 kB)
Downloading pyside6-6.9.2-cp39-abi3-win_amd64.whl (564 kB)
   ---------------------------------------- 564.6/564.6 kB 17.2 MB/s  0:00:00
Downloading pyside6_addons-6.9.2-cp39-abi3-win_amd64.whl (160.2 MB)
   ---------------------------------------- 160.2/160.2 MB 12.0 MB/s  0:00:13
Downloading pyside6_essentials-6.9.2-cp39-abi3-win_amd64.whl (72.6 MB)
   ---------------------------------------- 72.6/72.6 MB 12.1 MB/s  0:00:05
Downloading shiboken6-6.9.2-cp39-abi3-win_amd64.whl (1.2 MB)
   ---------------------------------------- 1.2/1.2 MB 14.9 MB/s  0:00:00
Using cached requests-2.32.5-py3-none-any.whl (64 kB)
Using cached charset_normalizer-3.4.3-cp313-cp313-win_amd64.whl (107 kB)
Using cached urllib3-2.5.0-py3-none-any.whl (129 kB)
Using cached certifi-2025.8.3-py3-none-any.whl (161 kB)
Installing collected packages: urllib3, shiboken6, charset_normalizer, certifi, requests, PySide6_Essentials, PySide6_Addons, PySide6

Successfully installed PySide6-6.9.2 PySide6_Addons-6.9.2 PySide6_Essentials-6.9.2 certifi-2025.8.3 charset_normalizer-3.4.3 requests-2.32.5 shiboken6-6.9.2 urllib3-2.5.0
```

### Command: Remove-Item dist\plc-agent-tray -Recurse -Force -ErrorAction SilentlyContinue (after deps)
```
(no output)
```

### Command: Remove-Item build\plc-agent-tray -Recurse -Force -ErrorAction SilentlyContinue (after deps)
```
(no output)
```

### Command: pyinstaller --noconfirm --clean plc-agent-tray.spec (after deps)
```
pyinstaller.exe : 96 INFO: PyInstaller: 6.15.0, contrib hooks: 2025.8
At line:1 char:166
+ ... ``'; $out = & pyinstaller --noconfirm --clean plc-agent-tray.spec 2>& ...
+                 ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (96 INFO: PyInst...b hooks: 2025.8:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 
97 INFO: Python: 3.13.3
120 INFO: Platform: Windows-11-10.0.26100-SP0
120 INFO: Python environment: C:\Users\pc\AppData\Local\Programs\Python\Python313
121 INFO: Removing temporary files and cleaning cache in C:\Users\pc\AppData\Local\pyinstaller
145 WARNING: Failed to collect submodules for 'PySide6.scripts.deploy_lib' because importing 
'PySide6.scripts.deploy_lib' raised: ModuleNotFoundError: No module named 'project_lib'
428 INFO: Module search paths (PYTHONPATH):
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\pyinstaller.exe',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\python313.zip',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\DLLs',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32\\lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\Pythonwin',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\setuptools\\_vendor',
 'D:\\Apps\\plc_logger_app\\plc_logger\\apps']
615 INFO: checking Analysis
616 INFO: Building Analysis because Analysis-00.toc is non existent
616 INFO: Running Analysis Analysis-00.toc
616 INFO: Target bytecode optimization level: 0
616 INFO: Initializing module dependency graph...
616 INFO: Initializing module graph hook caches...
623 INFO: Analyzing modules for base_library.zip ...
1145 INFO: Processing standard module hook 'hook-encodings.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2394 INFO: Processing standard module hook 'hook-pickle.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2901 INFO: Processing standard module hook 'hook-heapq.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3156 INFO: Caching module dependency graph...
3175 INFO: Looking for Python shared library...
3178 INFO: Using Python shared library: C:\Users\pc\AppData\Local\Programs\Python\Python313\python313.dll
3178 INFO: Analyzing D:\Apps\plc_logger_app\plc_logger\apps\agent-tray\main.py
3186 INFO: Processing standard module hook 'hook-PySide6.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3284 INFO: Processing standard module hook 'hook-shiboken6.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3370 INFO: Processing standard module hook 'hook-PySide6.QtNetwork.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3933 INFO: Processing standard module hook 'hook-PySide6.QtCore.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4405 INFO: Processing standard module hook 'hook-PySide6.QtGui.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4981 INFO: Processing standard module hook 'hook-PySide6.QtWidgets.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
5215 INFO: Analyzing hidden import 'PySide6.Qt3DAnimation'
5238 INFO: Processing standard module hook 'hook-PySide6.Qt3DAnimation.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
5362 INFO: Processing standard module hook 'hook-PySide6.Qt3DCore.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
5526 INFO: Processing standard module hook 'hook-PySide6.Qt3DRender.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6431 INFO: Processing standard module hook 'hook-PySide6.QtOpenGL.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6568 INFO: Analyzing hidden import 'PySide6.Qt3DExtras'
6611 INFO: Processing standard module hook 'hook-PySide6.Qt3DExtras.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6708 INFO: Analyzing hidden import 'PySide6.Qt3DInput'
6726 INFO: Processing standard module hook 'hook-PySide6.Qt3DInput.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6816 INFO: Analyzing hidden import 'PySide6.Qt3DLogic'
6823 INFO: Processing standard module hook 'hook-PySide6.Qt3DLogic.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6909 INFO: Analyzing hidden import 'PySide6.QtAsyncio'
7016 INFO: Processing standard module hook 'hook-multiprocessing.util.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7107 INFO: Processing standard module hook 'hook-xml.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7246 INFO: Processing standard module hook 'hook-_ctypes.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7461 INFO: Analyzing hidden import 'PySide6.QtAxContainer'
7475 INFO: Processing standard module hook 'hook-PySide6.QtAxContainer.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7562 INFO: Analyzing hidden import 'PySide6.QtBluetooth'
7604 INFO: Processing standard module hook 'hook-PySide6.QtBluetooth.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7693 INFO: Analyzing hidden import 'PySide6.QtCharts'
7754 INFO: Processing standard module hook 'hook-PySide6.QtCharts.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7858 INFO: Analyzing hidden import 'PySide6.QtConcurrent'
7868 INFO: Processing standard module hook 'hook-PySide6.QtConcurrent.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7951 INFO: Analyzing hidden import 'PySide6.QtDBus'
7975 INFO: Processing standard module hook 'hook-PySide6.QtDBus.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8066 INFO: Analyzing hidden import 'PySide6.QtDataVisualization'
8122 INFO: Processing standard module hook 'hook-PySide6.QtDataVisualization.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8221 INFO: Analyzing hidden import 'PySide6.QtDesigner'
8255 INFO: Processing standard module hook 'hook-PySide6.QtDesigner.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8402 INFO: Analyzing hidden import 'PySide6.QtExampleIcons'
8403 INFO: Analyzing hidden import 'PySide6.QtGraphs'
8479 INFO: Processing standard module hook 'hook-PySide6.QtGraphs.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8627 INFO: Processing standard module hook 'hook-PySide6.QtQml.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10042 INFO: Analyzing hidden import 'PySide6.QtGraphsWidgets'
10058 INFO: Processing standard module hook 'hook-PySide6.QtGraphsWidgets.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10197 INFO: Processing standard module hook 'hook-PySide6.QtQuick.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10306 INFO: Processing standard module hook 'hook-PySide6.QtQuickWidgets.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10393 INFO: Analyzing hidden import 'PySide6.QtHelp'
10411 INFO: Processing standard module hook 'hook-PySide6.QtHelp.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10505 INFO: Analyzing hidden import 'PySide6.QtHttpServer'
10521 INFO: Processing standard module hook 'hook-PySide6.QtHttpServer.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10611 INFO: Analyzing hidden import 'PySide6.QtLocation'
10648 INFO: Processing standard module hook 'hook-PySide6.QtLocation.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10780 INFO: Processing standard module hook 'hook-PySide6.QtPositioning.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10890 INFO: Analyzing hidden import 'PySide6.QtMultimedia'
10937 INFO: Processing standard module hook 'hook-PySide6.QtMultimedia.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11099 INFO: Analyzing hidden import 'PySide6.QtMultimediaWidgets'
11109 INFO: Processing standard module hook 'hook-PySide6.QtMultimediaWidgets.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11198 INFO: Analyzing hidden import 'PySide6.QtNetworkAuth'
11218 INFO: Processing standard module hook 'hook-PySide6.QtNetworkAuth.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11308 INFO: Analyzing hidden import 'PySide6.QtNfc'
11325 INFO: Processing standard module hook 'hook-PySide6.QtNfc.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11415 INFO: Analyzing hidden import 'PySide6.QtOpenGLWidgets'
11423 INFO: Processing standard module hook 'hook-PySide6.QtOpenGLWidgets.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11511 INFO: Analyzing hidden import 'PySide6.QtPdf'
11526 INFO: Processing standard module hook 'hook-PySide6.QtPdf.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11617 INFO: Analyzing hidden import 'PySide6.QtPdfWidgets'
11626 INFO: Processing standard module hook 'hook-PySide6.QtPdfWidgets.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11715 INFO: Analyzing hidden import 'PySide6.QtPrintSupport'
11731 INFO: Processing standard module hook 'hook-PySide6.QtPrintSupport.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11824 INFO: Analyzing hidden import 'PySide6.QtQuick3D'
11838 INFO: Processing standard module hook 'hook-PySide6.QtQuick3D.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11938 INFO: Analyzing hidden import 'PySide6.QtQuickControls2'
11946 INFO: Processing standard module hook 'hook-PySide6.QtQuickControls2.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12032 INFO: Analyzing hidden import 'PySide6.QtQuickTest'
12039 INFO: Analyzing hidden import 'PySide6.QtRemoteObjects'
12056 INFO: Processing standard module hook 'hook-PySide6.QtRemoteObjects.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12147 INFO: Analyzing hidden import 'PySide6.QtScxml'
12164 INFO: Processing standard module hook 'hook-PySide6.QtScxml.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12260 INFO: Analyzing hidden import 'PySide6.QtSensors'
12283 INFO: Processing standard module hook 'hook-PySide6.QtSensors.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12383 INFO: Analyzing hidden import 'PySide6.QtSerialBus'
12411 INFO: Processing standard module hook 'hook-PySide6.QtSerialBus.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12535 INFO: Analyzing hidden import 'PySide6.QtSerialPort'
12546 INFO: Processing standard module hook 'hook-PySide6.QtSerialPort.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12634 INFO: Analyzing hidden import 'PySide6.QtSpatialAudio'
12647 INFO: Processing standard module hook 'hook-PySide6.QtSpatialAudio.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12739 INFO: Analyzing hidden import 'PySide6.QtSql'
12768 INFO: Processing standard module hook 'hook-PySide6.QtSql.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12893 INFO: Analyzing hidden import 'PySide6.QtStateMachine'
12908 INFO: Processing standard module hook 'hook-PySide6.QtStateMachine.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12997 INFO: Analyzing hidden import 'PySide6.QtSvg'
13008 INFO: Processing standard module hook 'hook-PySide6.QtSvg.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13097 INFO: Analyzing hidden import 'PySide6.QtSvgWidgets'
13106 INFO: Processing standard module hook 'hook-PySide6.QtSvgWidgets.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13194 INFO: Analyzing hidden import 'PySide6.QtTest'
13209 INFO: Processing standard module hook 'hook-PySide6.QtTest.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13300 INFO: Analyzing hidden import 'PySide6.QtTextToSpeech'
13312 INFO: Processing standard module hook 'hook-PySide6.QtTextToSpeech.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13415 INFO: Analyzing hidden import 'PySide6.QtUiTools'
13423 INFO: Processing standard module hook 'hook-PySide6.QtUiTools.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13511 INFO: Analyzing hidden import 'PySide6.QtWebChannel'
13519 INFO: Processing standard module hook 'hook-PySide6.QtWebChannel.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13606 INFO: Analyzing hidden import 'PySide6.QtWebEngineCore'
13646 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineCore.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14048 INFO: Analyzing hidden import 'PySide6.QtWebEngineQuick'
14063 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineQuick.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14153 INFO: Analyzing hidden import 'PySide6.QtWebEngineWidgets'
14163 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineWidgets.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14248 INFO: Analyzing hidden import 'PySide6.QtWebSockets'
14262 INFO: Processing standard module hook 'hook-PySide6.QtWebSockets.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14349 INFO: Analyzing hidden import 'PySide6.QtWebView'
14355 INFO: Analyzing hidden import 'PySide6.QtXml'
14374 INFO: Processing standard module hook 'hook-PySide6.QtXml.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14459 INFO: Analyzing hidden import 'PySide6._config'
14460 INFO: Analyzing hidden import 'PySide6._git_pyside_version'
14460 INFO: Analyzing hidden import 'PySide6.scripts'
14460 INFO: Analyzing hidden import 'PySide6.scripts.deploy'
14464 INFO: Analyzing hidden import 'PySide6.scripts.metaobjectdump'
14473 INFO: Analyzing hidden import 'PySide6.scripts.project'
14481 INFO: Analyzing hidden import 'PySide6.scripts.project_lib'
14526 INFO: Processing standard module hook 'hook-xml.etree.cElementTree.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14558 INFO: Analyzing hidden import 'PySide6.scripts.pyside_tool'
14572 INFO: Processing standard module hook 'hook-sysconfig.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14575 INFO: Analyzing hidden import 'PySide6.scripts.qml'
14579 INFO: Analyzing hidden import 'PySide6.scripts.qtpy2cpp'
14581 INFO: Analyzing hidden import 'PySide6.support'
14581 INFO: Analyzing hidden import 'PySide6.support.deprecated'
14581 INFO: Analyzing hidden import 'PySide6.support.generate_pyi'
14583 INFO: Processing module hooks (post-graph stage)...
14746 INFO: Performing binary vs. data reclassification (2754 entries)
25166 INFO: Looking for ctypes DLLs
25170 INFO: Analyzing run-time hooks ...
25171 INFO: Including run-time hook 'pyi_rth_inspect.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
25173 INFO: Including run-time hook 'pyi_rth_pkgutil.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
25174 INFO: Including run-time hook 'pyi_rth_multiprocessing.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
25175 INFO: Including run-time hook 'pyi_rth_pyside6.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
25184 INFO: Processing pre-find-module-path hook 'hook-_pyi_rth_utils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs
\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_find_module_path'
25193 INFO: Processing standard module hook 'hook-_pyi_rth_utils.py' from 
'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
25241 INFO: Creating base_library.zip...
25267 INFO: Looking for dynamic libraries
25411 INFO: Extra DLL search directories (AddDllDirectory): 
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\shiboken6']
25411 INFO: Extra DLL search directories (PATH): 
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6']
27460 WARNING: Library not found: could not resolve 'OCI.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\
Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqloci.dll'.
27460 WARNING: Library not found: could not resolve 'MIMAPI64.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Progr
ams\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlmimer.dll'.
27460 WARNING: Library not found: could not resolve 'fbclient.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Progr
ams\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlibase.dll'.
27460 WARNING: Library not found: could not resolve 'LIBPQ.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs
\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlpsql.dll'.
27494 INFO: Warnings written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\warn-plc-agent-tray.txt
27507 INFO: Graph cross-reference written to 
D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\xref-plc-agent-tray.html
27549 INFO: checking PYZ
27550 INFO: Building PYZ because PYZ-00.toc is non existent
27550 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz
27773 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz completed 
successfully.
27780 INFO: checking PKG
27780 INFO: Building PKG because PKG-00.toc is non existent
27780 INFO: Building PKG (CArchive) plc-agent-tray.pkg
27799 INFO: Building PKG (CArchive) plc-agent-tray.pkg completed successfully.
27799 INFO: Bootloader C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\bootloader\Win
dows-64bit-intel\runw.exe
27799 INFO: checking EXE
27800 INFO: Building EXE because EXE-00.toc is non existent
27800 INFO: Building EXE from EXE-00.toc
27800 INFO: Copying bootloader EXE to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\plc-agent-tray.exe
27803 INFO: Copying icon to EXE
27805 INFO: Copying 0 resources to EXE
27805 INFO: Embedding manifest in EXE
27838 INFO: Appending PKG archive to EXE
27887 INFO: Fixing EXE headers
28190 INFO: Building EXE from EXE-00.toc completed successfully.
28206 INFO: checking COLLECT
28206 INFO: Building COLLECT because COLLECT-00.toc is non existent
28206 INFO: Removing dir D:\Apps\plc_logger_app\plc_logger\dist\plc-agent-tray
Traceback (most recent call last):
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\building\utils.py", line 
394, in _make_clean_directory
    os.remove(path)
    ~~~~~~~~~^^^^^^
PermissionError: [WinError 5] Access is denied: 'D:\\Apps\\plc_logger_app\\plc_logger\\dist\\plc-agent-tray'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Scripts\pyinstaller.exe\__main__.py", line 7, in <module>
    sys.exit(_console_script_run())
             ~~~~~~~~~~~~~~~~~~~^^
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\__main__.py", line 231, in 
_console_script_run
    run()
    ~~~^^
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\__main__.py", line 215, in 
run
    run_build(pyi_config, spec_file, **vars(args))
    ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\__main__.py", line 70, in 
run_build
    PyInstaller.building.build_main.main(pyi_config, spec_file, **kwargs)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\building\build_main.py", 
line 1282, in main
    build(specfile, distpath, workpath, clean_build)
    ~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\building\build_main.py", 
line 1220, in build
    exec(code, spec_namespace)
    ~~~~^^^^^^^^^^^^^^^^^^^^^^
  File "plc-agent-tray.spec", line 45, in <module>
    coll = COLLECT(
        exe,
    ...<6 lines>...
        name='plc-agent-tray'
    )
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\building\api.py", line 1150, 
in __init__
    self.__postinit__()
    ~~~~~~~~~~~~~~~~~^^
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\building\datastruct.py", 
line 184, in __postinit__
    self.assemble()
    ~~~~~~~~~~~~~^^
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\building\api.py", line 1162, 
in assemble
    _make_clean_directory(self.name)
    ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\building\utils.py", line 
396, in _make_clean_directory
    _rmtree(path)
    ~~~~~~~^^^^^^
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\building\utils.py", line 
421, in _rmtree
    shutil.rmtree(path)
    ~~~~~~~~~~~~~^^^^^^
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\shutil.py", line 790, in rmtree
    return _rmtree_unsafe(path, onexc)
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\shutil.py", line 629, in _rmtree_unsafe
    onexc(os.unlink, fullname, err)
    ~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\shutil.py", line 625, in _rmtree_unsafe
    os.unlink(fullname)
    ~~~~~~~~~^^^^^^^^^^
PermissionError: [WinError 5] Access is denied: 
'D:\\Apps\\plc_logger_app\\plc_logger\\dist\\plc-agent-tray\\_internal\\python313.dll'
```

### Command: Get-Process plc-agent-tray -ErrorAction SilentlyContinue | Stop-Process -Force (pre-clean)
```
No running process
```

### Command: Remove-Item dist\plc-agent-tray -Recurse -Force -ErrorAction SilentlyContinue (recover)
```
(no output)
```

### Command: Remove-Item build\plc-agent-tray -Recurse -Force -ErrorAction SilentlyContinue (recover)
```
(no output)
```

### Command: pyinstaller --noconfirm --clean plc-agent-tray.spec (recover)
```
92 INFO: PyInstaller: 6.15.0, contrib hooks: 2025.8
92 INFO: Python: 3.13.3
106 INFO: Platform: Windows-11-10.0.26100-SP0
106 INFO: Python environment: C:\Users\pc\AppData\Local\Programs\Python\Python313
108 INFO: Removing temporary files and cleaning cache in C:\Users\pc\AppData\Local\pyinstaller
117 WARNING: Failed to collect submodules for 'PySide6.scripts.deploy_lib' because importing 'PySide6.scripts.deploy_lib' raised: ModuleNotFoundError: No module named 'project_lib'
342 INFO: Module search paths (PYTHONPATH):
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\pyinstaller.exe',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\python313.zip',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\DLLs',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32\\lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\Pythonwin',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\setuptools\\_vendor',
 'D:\\Apps\\plc_logger_app\\plc_logger\\apps']
524 INFO: checking Analysis
524 INFO: Building Analysis because Analysis-00.toc is non existent
524 INFO: Running Analysis Analysis-00.toc
524 INFO: Target bytecode optimization level: 0
524 INFO: Initializing module dependency graph...
525 INFO: Initializing module graph hook caches...
531 INFO: Analyzing modules for base_library.zip ...
1132 INFO: Processing standard module hook 'hook-heapq.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
1188 INFO: Processing standard module hook 'hook-encodings.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2343 INFO: Processing standard module hook 'hook-pickle.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2995 INFO: Caching module dependency graph...
3013 INFO: Looking for Python shared library...
3015 INFO: Using Python shared library: C:\Users\pc\AppData\Local\Programs\Python\Python313\python313.dll
3015 INFO: Analyzing D:\Apps\plc_logger_app\plc_logger\apps\agent-tray\main.py
3023 INFO: Processing standard module hook 'hook-PySide6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3118 INFO: Processing standard module hook 'hook-shiboken6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3186 INFO: Processing standard module hook 'hook-PySide6.QtNetwork.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3653 INFO: Processing standard module hook 'hook-PySide6.QtCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4079 INFO: Processing standard module hook 'hook-PySide6.QtGui.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4566 INFO: Processing standard module hook 'hook-PySide6.QtWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4764 INFO: Analyzing hidden import 'PySide6.Qt3DAnimation'
4779 INFO: Processing standard module hook 'hook-PySide6.Qt3DAnimation.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4877 INFO: Processing standard module hook 'hook-PySide6.Qt3DCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
5021 INFO: Processing standard module hook 'hook-PySide6.Qt3DRender.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
5894 INFO: Processing standard module hook 'hook-PySide6.QtOpenGL.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6011 INFO: Analyzing hidden import 'PySide6.Qt3DExtras'
6045 INFO: Processing standard module hook 'hook-PySide6.Qt3DExtras.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6128 INFO: Analyzing hidden import 'PySide6.Qt3DInput'
6140 INFO: Processing standard module hook 'hook-PySide6.Qt3DInput.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6220 INFO: Analyzing hidden import 'PySide6.Qt3DLogic'
6221 INFO: Processing standard module hook 'hook-PySide6.Qt3DLogic.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6301 INFO: Analyzing hidden import 'PySide6.QtAsyncio'
6402 INFO: Processing standard module hook 'hook-multiprocessing.util.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6490 INFO: Processing standard module hook 'hook-xml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6623 INFO: Processing standard module hook 'hook-_ctypes.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6828 INFO: Analyzing hidden import 'PySide6.QtAxContainer'
6834 INFO: Processing standard module hook 'hook-PySide6.QtAxContainer.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6913 INFO: Analyzing hidden import 'PySide6.QtBluetooth'
6947 INFO: Processing standard module hook 'hook-PySide6.QtBluetooth.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7025 INFO: Analyzing hidden import 'PySide6.QtCharts'
7077 INFO: Processing standard module hook 'hook-PySide6.QtCharts.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7166 INFO: Analyzing hidden import 'PySide6.QtConcurrent'
7169 INFO: Processing standard module hook 'hook-PySide6.QtConcurrent.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7248 INFO: Analyzing hidden import 'PySide6.QtDBus'
7265 INFO: Processing standard module hook 'hook-PySide6.QtDBus.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7346 INFO: Analyzing hidden import 'PySide6.QtDataVisualization'
7393 INFO: Processing standard module hook 'hook-PySide6.QtDataVisualization.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7480 INFO: Analyzing hidden import 'PySide6.QtDesigner'
7497 INFO: Processing standard module hook 'hook-PySide6.QtDesigner.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7614 INFO: Analyzing hidden import 'PySide6.QtExampleIcons'
7614 INFO: Analyzing hidden import 'PySide6.QtGraphs'
7678 INFO: Processing standard module hook 'hook-PySide6.QtGraphs.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7792 INFO: Processing standard module hook 'hook-PySide6.QtQml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8233 INFO: Analyzing hidden import 'PySide6.QtGraphsWidgets'
8367 INFO: Processing standard module hook 'hook-PySide6.QtQuick.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8461 INFO: Processing standard module hook 'hook-PySide6.QtQuickWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8543 INFO: Analyzing hidden import 'PySide6.QtHelp'
8553 INFO: Processing standard module hook 'hook-PySide6.QtHelp.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8634 INFO: Analyzing hidden import 'PySide6.QtHttpServer'
8640 INFO: Processing standard module hook 'hook-PySide6.QtHttpServer.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8721 INFO: Analyzing hidden import 'PySide6.QtLocation'
8749 INFO: Processing standard module hook 'hook-PySide6.QtLocation.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8859 INFO: Processing standard module hook 'hook-PySide6.QtPositioning.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8953 INFO: Analyzing hidden import 'PySide6.QtMultimedia'
8992 INFO: Processing standard module hook 'hook-PySide6.QtMultimedia.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9102 INFO: Analyzing hidden import 'PySide6.QtMultimediaWidgets'
9103 INFO: Processing standard module hook 'hook-PySide6.QtMultimediaWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9185 INFO: Analyzing hidden import 'PySide6.QtNetworkAuth'
9197 INFO: Processing standard module hook 'hook-PySide6.QtNetworkAuth.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9278 INFO: Analyzing hidden import 'PySide6.QtNfc'
9289 INFO: Processing standard module hook 'hook-PySide6.QtNfc.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9368 INFO: Analyzing hidden import 'PySide6.QtOpenGLWidgets'
9370 INFO: Processing standard module hook 'hook-PySide6.QtOpenGLWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9451 INFO: Analyzing hidden import 'PySide6.QtPdf'
9459 INFO: Processing standard module hook 'hook-PySide6.QtPdf.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9543 INFO: Analyzing hidden import 'PySide6.QtPdfWidgets'
9546 INFO: Processing standard module hook 'hook-PySide6.QtPdfWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9625 INFO: Analyzing hidden import 'PySide6.QtPrintSupport'
9634 INFO: Processing standard module hook 'hook-PySide6.QtPrintSupport.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9716 INFO: Analyzing hidden import 'PySide6.QtQuick3D'
9818 INFO: Analyzing hidden import 'PySide6.QtQuickControls2'
9819 INFO: Processing standard module hook 'hook-PySide6.QtQuickControls2.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9899 INFO: Analyzing hidden import 'PySide6.QtQuickTest'
9899 INFO: Analyzing hidden import 'PySide6.QtRemoteObjects'
9909 INFO: Processing standard module hook 'hook-PySide6.QtRemoteObjects.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9990 INFO: Analyzing hidden import 'PySide6.QtScxml'
10000 INFO: Processing standard module hook 'hook-PySide6.QtScxml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10084 INFO: Analyzing hidden import 'PySide6.QtSensors'
10100 INFO: Processing standard module hook 'hook-PySide6.QtSensors.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10187 INFO: Analyzing hidden import 'PySide6.QtSerialBus'
10206 INFO: Processing standard module hook 'hook-PySide6.QtSerialBus.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10303 INFO: Analyzing hidden import 'PySide6.QtSerialPort'
10307 INFO: Processing standard module hook 'hook-PySide6.QtSerialPort.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10390 INFO: Analyzing hidden import 'PySide6.QtSpatialAudio'
10397 INFO: Processing standard module hook 'hook-PySide6.QtSpatialAudio.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10478 INFO: Analyzing hidden import 'PySide6.QtSql'
10498 INFO: Processing standard module hook 'hook-PySide6.QtSql.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10597 INFO: Analyzing hidden import 'PySide6.QtStateMachine'
10605 INFO: Processing standard module hook 'hook-PySide6.QtStateMachine.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10685 INFO: Analyzing hidden import 'PySide6.QtSvg'
10688 INFO: Processing standard module hook 'hook-PySide6.QtSvg.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10767 INFO: Analyzing hidden import 'PySide6.QtSvgWidgets'
10769 INFO: Processing standard module hook 'hook-PySide6.QtSvgWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10850 INFO: Analyzing hidden import 'PySide6.QtTest'
10858 INFO: Processing standard module hook 'hook-PySide6.QtTest.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10942 INFO: Analyzing hidden import 'PySide6.QtTextToSpeech'
10946 INFO: Processing standard module hook 'hook-PySide6.QtTextToSpeech.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11037 INFO: Analyzing hidden import 'PySide6.QtUiTools'
11039 INFO: Processing standard module hook 'hook-PySide6.QtUiTools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11120 INFO: Analyzing hidden import 'PySide6.QtWebChannel'
11121 INFO: Processing standard module hook 'hook-PySide6.QtWebChannel.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11201 INFO: Analyzing hidden import 'PySide6.QtWebEngineCore'
11232 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11360 INFO: Analyzing hidden import 'PySide6.QtWebEngineQuick'
11363 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineQuick.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11446 INFO: Analyzing hidden import 'PySide6.QtWebEngineWidgets'
11449 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11531 INFO: Analyzing hidden import 'PySide6.QtWebSockets'
11537 INFO: Processing standard module hook 'hook-PySide6.QtWebSockets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11617 INFO: Analyzing hidden import 'PySide6.QtWebView'
11618 INFO: Analyzing hidden import 'PySide6.QtXml'
11630 INFO: Processing standard module hook 'hook-PySide6.QtXml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11713 INFO: Analyzing hidden import 'PySide6._config'
11714 INFO: Analyzing hidden import 'PySide6._git_pyside_version'
11715 INFO: Analyzing hidden import 'PySide6.scripts'
11715 INFO: Analyzing hidden import 'PySide6.scripts.deploy'
11718 INFO: Analyzing hidden import 'PySide6.scripts.metaobjectdump'
11728 INFO: Analyzing hidden import 'PySide6.scripts.project'
11736 INFO: Analyzing hidden import 'PySide6.scripts.project_lib'
11778 INFO: Processing standard module hook 'hook-xml.etree.cElementTree.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11809 INFO: Analyzing hidden import 'PySide6.scripts.pyside_tool'
11821 INFO: Processing standard module hook 'hook-sysconfig.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11979 INFO: Performing binary vs. data reclassification (2754 entries)
12117 INFO: Looking for ctypes DLLs
12120 INFO: Analyzing run-time hooks ...
12121 INFO: Including run-time hook 'pyi_rth_inspect.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
12122 INFO: Including run-time hook 'pyi_rth_pkgutil.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
12123 INFO: Including run-time hook 'pyi_rth_multiprocessing.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
12125 INFO: Including run-time hook 'pyi_rth_pyside6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
12126 INFO: Processing pre-find-module-path hook 'hook-_pyi_rth_utils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_find_module_path'
12127 INFO: Processing standard module hook 'hook-_pyi_rth_utils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12163 INFO: Creating base_library.zip...
12187 INFO: Looking for dynamic libraries
12328 INFO: Extra DLL search directories (AddDllDirectory): ['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\shiboken6']
12328 INFO: Extra DLL search directories (PATH): ['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6']
14149 WARNING: Library not found: could not resolve 'OCI.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqloci.dll'.
14149 WARNING: Library not found: could not resolve 'LIBPQ.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlpsql.dll'.
14149 WARNING: Library not found: could not resolve 'MIMAPI64.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlmimer.dll'.
14149 WARNING: Library not found: could not resolve 'fbclient.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlibase.dll'.
14183 INFO: Warnings written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\warn-plc-agent-tray.txt
14197 INFO: Graph cross-reference written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\xref-plc-agent-tray.html
14238 INFO: checking PYZ
14238 INFO: Building PYZ because PYZ-00.toc is non existent
14238 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz
14455 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz completed successfully.
14462 INFO: checking PKG
14462 INFO: Building PKG because PKG-00.toc is non existent
14462 INFO: Building PKG (CArchive) plc-agent-tray.pkg
14481 INFO: Building PKG (CArchive) plc-agent-tray.pkg completed successfully.
14481 INFO: Bootloader C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\bootloader\Windows-64bit-intel\runw.exe
14481 INFO: checking EXE
14481 INFO: Building EXE because EXE-00.toc is non existent
14481 INFO: Building EXE from EXE-00.toc
14481 INFO: Copying bootloader EXE to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\plc-agent-tray.exe
14484 INFO: Copying icon to EXE
14486 INFO: Copying 0 resources to EXE
14486 INFO: Embedding manifest in EXE
14523 INFO: Appending PKG archive to EXE
14565 INFO: Fixing EXE headers
14866 INFO: Building EXE from EXE-00.toc completed successfully.
14881 INFO: checking COLLECT
14881 INFO: Building COLLECT because COLLECT-00.toc is non existent
14881 INFO: Building COLLECT COLLECT-00.toc
15950 INFO: Building COLLECT COLLECT-00.toc completed successfully.
15982 INFO: Build complete! The results are available in: D:\Apps\plc_logger_app\plc_logger\dist
```

### Command: pyinstaller --noconfirm --clean plc-agent-tray.spec (module import fix)
```
93 INFO: PyInstaller: 6.15.0, contrib hooks: 2025.8
93 INFO: Python: 3.13.3
110 INFO: Platform: Windows-11-10.0.26100-SP0
110 INFO: Python environment: C:\Users\pc\AppData\Local\Programs\Python\Python313
111 INFO: Removing temporary files and cleaning cache in C:\Users\pc\AppData\Local\pyinstaller
120 WARNING: Failed to collect submodules for 'PySide6.scripts.deploy_lib' because importing 'PySide6.scripts.deploy_lib' raised: ModuleNotFoundError: No module named 'project_lib'
348 INFO: Module search paths (PYTHONPATH):
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\pyinstaller.exe',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\python313.zip',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\DLLs',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32\\lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\Pythonwin',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\setuptools\\_vendor',
 'D:\\Apps\\plc_logger_app\\plc_logger\\apps']
533 INFO: checking Analysis
533 INFO: Building Analysis because Analysis-00.toc is non existent
533 INFO: Running Analysis Analysis-00.toc
533 INFO: Target bytecode optimization level: 0
533 INFO: Initializing module dependency graph...
534 INFO: Initializing module graph hook caches...
540 INFO: Analyzing modules for base_library.zip ...
1082 INFO: Processing standard module hook 'hook-encodings.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2292 INFO: Processing standard module hook 'hook-pickle.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2754 INFO: Processing standard module hook 'hook-heapq.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3003 INFO: Caching module dependency graph...
3022 INFO: Looking for Python shared library...
3025 INFO: Using Python shared library: C:\Users\pc\AppData\Local\Programs\Python\Python313\python313.dll
3025 INFO: Analyzing D:\Apps\plc_logger_app\plc_logger\apps\agent-tray\main.py
System.Management.Automation.RemoteException
Syntax error in D:\Apps\plc_logger_app\plc_logger\apps\agent-tray\main.py
  File "D:\Apps\plc_logger_app\plc_logger\apps\agent-tray\main.py", line 21
     ProcessEvent = process_manager.ProcessEvent`r`n
                                                ^
 SyntaxError: invalid syntax
System.Management.Automation.RemoteException
```

### Command: pyinstaller --noconfirm --clean plc-agent-tray.spec (module import fix retry)
```
96 INFO: PyInstaller: 6.15.0, contrib hooks: 2025.8
97 INFO: Python: 3.13.3
113 INFO: Platform: Windows-11-10.0.26100-SP0
113 INFO: Python environment: C:\Users\pc\AppData\Local\Programs\Python\Python313
114 INFO: Removing temporary files and cleaning cache in C:\Users\pc\AppData\Local\pyinstaller
119 WARNING: Failed to collect submodules for 'PySide6.scripts.deploy_lib' because importing 'PySide6.scripts.deploy_lib' raised: ModuleNotFoundError: No module named 'project_lib'
352 INFO: Module search paths (PYTHONPATH):
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\pyinstaller.exe',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\python313.zip',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\DLLs',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32\\lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\Pythonwin',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\setuptools\\_vendor',
 'D:\\Apps\\plc_logger_app\\plc_logger\\apps']
527 INFO: checking Analysis
527 INFO: Building Analysis because Analysis-00.toc is non existent
527 INFO: Running Analysis Analysis-00.toc
527 INFO: Target bytecode optimization level: 0
527 INFO: Initializing module dependency graph...
528 INFO: Initializing module graph hook caches...
534 INFO: Analyzing modules for base_library.zip ...
1217 INFO: Processing standard module hook 'hook-heapq.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
1269 INFO: Processing standard module hook 'hook-encodings.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2250 INFO: Processing standard module hook 'hook-pickle.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2952 INFO: Caching module dependency graph...
2971 INFO: Looking for Python shared library...
2974 INFO: Using Python shared library: C:\Users\pc\AppData\Local\Programs\Python\Python313\python313.dll
2974 INFO: Analyzing D:\Apps\plc_logger_app\plc_logger\apps\agent-tray\main.py
2982 INFO: Processing standard module hook 'hook-PySide6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3073 INFO: Processing standard module hook 'hook-shiboken6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3143 INFO: Processing standard module hook 'hook-PySide6.QtNetwork.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3607 INFO: Processing standard module hook 'hook-PySide6.QtCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4042 INFO: Processing standard module hook 'hook-PySide6.QtGui.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4540 INFO: Processing standard module hook 'hook-PySide6.QtWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4747 INFO: Analyzing hidden import 'PySide6.Qt3DAnimation'
4762 INFO: Processing standard module hook 'hook-PySide6.Qt3DAnimation.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4861 INFO: Processing standard module hook 'hook-PySide6.Qt3DCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
5008 INFO: Processing standard module hook 'hook-PySide6.Qt3DRender.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
5886 INFO: Processing standard module hook 'hook-PySide6.QtOpenGL.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6006 INFO: Analyzing hidden import 'PySide6.Qt3DExtras'
6040 INFO: Processing standard module hook 'hook-PySide6.Qt3DExtras.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6126 INFO: Analyzing hidden import 'PySide6.Qt3DInput'
6137 INFO: Processing standard module hook 'hook-PySide6.Qt3DInput.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6217 INFO: Analyzing hidden import 'PySide6.Qt3DLogic'
6218 INFO: Processing standard module hook 'hook-PySide6.Qt3DLogic.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6300 INFO: Analyzing hidden import 'PySide6.QtAsyncio'
6402 INFO: Processing standard module hook 'hook-multiprocessing.util.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6491 INFO: Processing standard module hook 'hook-xml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6623 INFO: Processing standard module hook 'hook-_ctypes.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6831 INFO: Analyzing hidden import 'PySide6.QtAxContainer'
6836 INFO: Processing standard module hook 'hook-PySide6.QtAxContainer.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
6919 INFO: Analyzing hidden import 'PySide6.QtBluetooth'
6954 INFO: Processing standard module hook 'hook-PySide6.QtBluetooth.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7034 INFO: Analyzing hidden import 'PySide6.QtCharts'
7086 INFO: Processing standard module hook 'hook-PySide6.QtCharts.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7174 INFO: Analyzing hidden import 'PySide6.QtConcurrent'
7177 INFO: Processing standard module hook 'hook-PySide6.QtConcurrent.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7254 INFO: Analyzing hidden import 'PySide6.QtDBus'
7271 INFO: Processing standard module hook 'hook-PySide6.QtDBus.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7350 INFO: Analyzing hidden import 'PySide6.QtDataVisualization'
7397 INFO: Processing standard module hook 'hook-PySide6.QtDataVisualization.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7482 INFO: Analyzing hidden import 'PySide6.QtDesigner'
7498 INFO: Processing standard module hook 'hook-PySide6.QtDesigner.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7615 INFO: Analyzing hidden import 'PySide6.QtExampleIcons'
7615 INFO: Analyzing hidden import 'PySide6.QtGraphs'
7681 INFO: Processing standard module hook 'hook-PySide6.QtGraphs.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7793 INFO: Processing standard module hook 'hook-PySide6.QtQml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8241 INFO: Analyzing hidden import 'PySide6.QtGraphsWidgets'
8373 INFO: Processing standard module hook 'hook-PySide6.QtQuick.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8465 INFO: Processing standard module hook 'hook-PySide6.QtQuickWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8546 INFO: Analyzing hidden import 'PySide6.QtHelp'
8555 INFO: Processing standard module hook 'hook-PySide6.QtHelp.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8639 INFO: Analyzing hidden import 'PySide6.QtHttpServer'
8646 INFO: Processing standard module hook 'hook-PySide6.QtHttpServer.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8728 INFO: Analyzing hidden import 'PySide6.QtLocation'
8757 INFO: Processing standard module hook 'hook-PySide6.QtLocation.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8870 INFO: Processing standard module hook 'hook-PySide6.QtPositioning.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8964 INFO: Analyzing hidden import 'PySide6.QtMultimedia'
9003 INFO: Processing standard module hook 'hook-PySide6.QtMultimedia.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9111 INFO: Analyzing hidden import 'PySide6.QtMultimediaWidgets'
9112 INFO: Processing standard module hook 'hook-PySide6.QtMultimediaWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9195 INFO: Analyzing hidden import 'PySide6.QtNetworkAuth'
9207 INFO: Processing standard module hook 'hook-PySide6.QtNetworkAuth.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9288 INFO: Analyzing hidden import 'PySide6.QtNfc'
9298 INFO: Processing standard module hook 'hook-PySide6.QtNfc.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9380 INFO: Analyzing hidden import 'PySide6.QtOpenGLWidgets'
9382 INFO: Processing standard module hook 'hook-PySide6.QtOpenGLWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9463 INFO: Analyzing hidden import 'PySide6.QtPdf'
9471 INFO: Processing standard module hook 'hook-PySide6.QtPdf.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9557 INFO: Analyzing hidden import 'PySide6.QtPdfWidgets'
9560 INFO: Processing standard module hook 'hook-PySide6.QtPdfWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9652 INFO: Analyzing hidden import 'PySide6.QtPrintSupport'
9661 INFO: Processing standard module hook 'hook-PySide6.QtPrintSupport.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9751 INFO: Analyzing hidden import 'PySide6.QtQuick3D'
9849 INFO: Analyzing hidden import 'PySide6.QtQuickControls2'
9850 INFO: Processing standard module hook 'hook-PySide6.QtQuickControls2.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9929 INFO: Analyzing hidden import 'PySide6.QtQuickTest'
9930 INFO: Analyzing hidden import 'PySide6.QtRemoteObjects'
9939 INFO: Processing standard module hook 'hook-PySide6.QtRemoteObjects.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10020 INFO: Analyzing hidden import 'PySide6.QtScxml'
10030 INFO: Processing standard module hook 'hook-PySide6.QtScxml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10114 INFO: Analyzing hidden import 'PySide6.QtSensors'
10130 INFO: Processing standard module hook 'hook-PySide6.QtSensors.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10216 INFO: Analyzing hidden import 'PySide6.QtSerialBus'
10235 INFO: Processing standard module hook 'hook-PySide6.QtSerialBus.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10332 INFO: Analyzing hidden import 'PySide6.QtSerialPort'
10337 INFO: Processing standard module hook 'hook-PySide6.QtSerialPort.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10418 INFO: Analyzing hidden import 'PySide6.QtSpatialAudio'
10425 INFO: Processing standard module hook 'hook-PySide6.QtSpatialAudio.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10506 INFO: Analyzing hidden import 'PySide6.QtSql'
10525 INFO: Processing standard module hook 'hook-PySide6.QtSql.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10624 INFO: Analyzing hidden import 'PySide6.QtStateMachine'
10633 INFO: Processing standard module hook 'hook-PySide6.QtStateMachine.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10712 INFO: Analyzing hidden import 'PySide6.QtSvg'
10716 INFO: Processing standard module hook 'hook-PySide6.QtSvg.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10798 INFO: Analyzing hidden import 'PySide6.QtSvgWidgets'
10799 INFO: Processing standard module hook 'hook-PySide6.QtSvgWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10878 INFO: Analyzing hidden import 'PySide6.QtTest'
10887 INFO: Processing standard module hook 'hook-PySide6.QtTest.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10969 INFO: Analyzing hidden import 'PySide6.QtTextToSpeech'
10974 INFO: Processing standard module hook 'hook-PySide6.QtTextToSpeech.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11064 INFO: Analyzing hidden import 'PySide6.QtUiTools'
11065 INFO: Processing standard module hook 'hook-PySide6.QtUiTools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11147 INFO: Analyzing hidden import 'PySide6.QtWebChannel'
11149 INFO: Processing standard module hook 'hook-PySide6.QtWebChannel.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11228 INFO: Analyzing hidden import 'PySide6.QtWebEngineCore'
11260 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11388 INFO: Analyzing hidden import 'PySide6.QtWebEngineQuick'
11392 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineQuick.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11477 INFO: Analyzing hidden import 'PySide6.QtWebEngineWidgets'
11480 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11561 INFO: Analyzing hidden import 'PySide6.QtWebSockets'
11567 INFO: Processing standard module hook 'hook-PySide6.QtWebSockets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11648 INFO: Analyzing hidden import 'PySide6.QtWebView'
11649 INFO: Analyzing hidden import 'PySide6.QtXml'
11661 INFO: Processing standard module hook 'hook-PySide6.QtXml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11741 INFO: Analyzing hidden import 'PySide6._config'
11741 INFO: Analyzing hidden import 'PySide6._git_pyside_version'
11742 INFO: Analyzing hidden import 'PySide6.scripts'
11742 INFO: Analyzing hidden import 'PySide6.scripts.deploy'
11745 INFO: Analyzing hidden import 'PySide6.scripts.metaobjectdump'
11755 INFO: Analyzing hidden import 'PySide6.scripts.project'
11763 INFO: Analyzing hidden import 'PySide6.scripts.project_lib'
11806 INFO: Processing standard module hook 'hook-xml.etree.cElementTree.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11837 INFO: Analyzing hidden import 'PySide6.scripts.pyside_tool'
11850 INFO: Processing standard module hook 'hook-sysconfig.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11853 INFO: Analyzing hidden import 'PySide6.scripts.qml'
11857 INFO: Analyzing hidden import 'PySide6.scripts.qtpy2cpp'
11858 INFO: Analyzing hidden import 'PySide6.support'
11859 INFO: Analyzing hidden import 'PySide6.support.deprecated'
11859 INFO: Analyzing hidden import 'PySide6.support.generate_pyi'
11861 INFO: Processing module hooks (post-graph stage)...
12008 INFO: Performing binary vs. data reclassification (2754 entries)
12144 INFO: Looking for ctypes DLLs
12147 INFO: Analyzing run-time hooks ...
12148 INFO: Including run-time hook 'pyi_rth_inspect.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
12150 INFO: Including run-time hook 'pyi_rth_pkgutil.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
12151 INFO: Including run-time hook 'pyi_rth_multiprocessing.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
12152 INFO: Including run-time hook 'pyi_rth_pyside6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
12153 INFO: Processing pre-find-module-path hook 'hook-_pyi_rth_utils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_find_module_path'
12154 INFO: Processing standard module hook 'hook-_pyi_rth_utils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12190 INFO: Creating base_library.zip...
12214 INFO: Looking for dynamic libraries
12351 INFO: Extra DLL search directories (AddDllDirectory): ['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\shiboken6']
12351 INFO: Extra DLL search directories (PATH): ['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6']
14227 WARNING: Library not found: could not resolve 'OCI.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqloci.dll'.
14227 WARNING: Library not found: could not resolve 'MIMAPI64.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlmimer.dll'.
14227 WARNING: Library not found: could not resolve 'LIBPQ.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlpsql.dll'.
14227 WARNING: Library not found: could not resolve 'fbclient.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlibase.dll'.
14263 INFO: Warnings written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\warn-plc-agent-tray.txt
14275 INFO: Graph cross-reference written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\xref-plc-agent-tray.html
14318 INFO: checking PYZ
14318 INFO: Building PYZ because PYZ-00.toc is non existent
14318 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz
14534 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz completed successfully.
14540 INFO: checking PKG
14540 INFO: Building PKG because PKG-00.toc is non existent
14540 INFO: Building PKG (CArchive) plc-agent-tray.pkg
14557 INFO: Building PKG (CArchive) plc-agent-tray.pkg completed successfully.
14557 INFO: Bootloader C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\bootloader\Windows-64bit-intel\runw.exe
14557 INFO: checking EXE
14558 INFO: Building EXE because EXE-00.toc is non existent
14558 INFO: Building EXE from EXE-00.toc
14558 INFO: Copying bootloader EXE to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\plc-agent-tray.exe
14560 INFO: Copying icon to EXE
14562 INFO: Copying 0 resources to EXE
14562 INFO: Embedding manifest in EXE
14599 INFO: Appending PKG archive to EXE
14641 INFO: Fixing EXE headers
14943 INFO: Building EXE from EXE-00.toc completed successfully.
14958 INFO: checking COLLECT
14959 INFO: Building COLLECT because COLLECT-00.toc is non existent
14959 INFO: Building COLLECT COLLECT-00.toc
15961 INFO: Building COLLECT COLLECT-00.toc completed successfully.
15993 INFO: Build complete! The results are available in: D:\Apps\plc_logger_app\plc_logger\dist
```

### Command: pyinstaller --noconfirm --clean plc-agent-tray.spec (pathex fix)
```
101 INFO: PyInstaller: 6.15.0, contrib hooks: 2025.8
102 INFO: Python: 3.13.3
118 INFO: Platform: Windows-11-10.0.26100-SP0
118 INFO: Python environment: C:\Users\pc\AppData\Local\Programs\Python\Python313
119 INFO: Removing temporary files and cleaning cache in C:\Users\pc\AppData\Local\pyinstaller
125 WARNING: Failed to collect submodules for 'PySide6.scripts.deploy_lib' because importing 'PySide6.scripts.deploy_lib' raised: ModuleNotFoundError: No module named 'project_lib'
388 INFO: Module search paths (PYTHONPATH):
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\pyinstaller.exe',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\python313.zip',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\DLLs',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32\\lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\Pythonwin',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\setuptools\\_vendor',
 'D:\\Apps\\plc_logger_app\\plc_logger\\apps',
 'D:\\Apps\\plc_logger_app\\plc_logger\\apps\\agent-tray']
570 INFO: checking Analysis
570 INFO: Building Analysis because Analysis-00.toc is non existent
570 INFO: Running Analysis Analysis-00.toc
570 INFO: Target bytecode optimization level: 0
570 INFO: Initializing module dependency graph...
571 INFO: Initializing module graph hook caches...
577 INFO: Analyzing modules for base_library.zip ...
1273 INFO: Processing standard module hook 'hook-heapq.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
1326 INFO: Processing standard module hook 'hook-encodings.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2686 INFO: Processing standard module hook 'hook-pickle.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3417 INFO: Caching module dependency graph...
3437 INFO: Looking for Python shared library...
3440 INFO: Using Python shared library: C:\Users\pc\AppData\Local\Programs\Python\Python313\python313.dll
3440 INFO: Analyzing D:\Apps\plc_logger_app\plc_logger\apps\agent-tray\main.py
3449 INFO: Processing standard module hook 'hook-PySide6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3544 INFO: Processing standard module hook 'hook-shiboken6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3616 INFO: Processing standard module hook 'hook-PySide6.QtNetwork.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4111 INFO: Processing standard module hook 'hook-PySide6.QtCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4573 INFO: Processing standard module hook 'hook-PySide6.QtGui.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
5106 INFO: Processing standard module hook 'hook-PySide6.QtWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
5222 INFO: Processing pre-safe-import-module hook 'hook-win32com.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\pre_safe_import_module'
5302 INFO: Processing standard module hook 'hook-win32com.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
5307 INFO: Processing standard module hook 'hook-pythoncom.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
5353 INFO: Processing standard module hook 'hook-pywintypes.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
5820 INFO: Processing standard module hook 'hook-urllib3.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
5926 INFO: Processing pre-safe-import-module hook 'hook-typing_extensions.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
5927 INFO: SetuptoolsInfo: initializing cached setuptools info...
8031 INFO: Processing standard module hook 'hook-multiprocessing.util.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8080 INFO: Processing standard module hook 'hook-xml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8233 INFO: Processing standard module hook 'hook-_ctypes.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8804 INFO: Processing standard module hook 'hook-charset_normalizer.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
8886 INFO: Processing standard module hook 'hook-cryptography.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
9388 INFO: hook-cryptography: cryptography does not seem to be using dynamically linked OpenSSL.
9585 INFO: Processing standard module hook 'hook-certifi.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
9693 INFO: Analyzing hidden import 'PySide6.Qt3DAnimation'
9709 INFO: Processing standard module hook 'hook-PySide6.Qt3DAnimation.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9814 INFO: Processing standard module hook 'hook-PySide6.Qt3DCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9969 INFO: Processing standard module hook 'hook-PySide6.Qt3DRender.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10898 INFO: Processing standard module hook 'hook-PySide6.QtOpenGL.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11025 INFO: Analyzing hidden import 'PySide6.Qt3DExtras'
11061 INFO: Processing standard module hook 'hook-PySide6.Qt3DExtras.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11151 INFO: Analyzing hidden import 'PySide6.Qt3DInput'
11163 INFO: Processing standard module hook 'hook-PySide6.Qt3DInput.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11249 INFO: Analyzing hidden import 'PySide6.Qt3DLogic'
11250 INFO: Processing standard module hook 'hook-PySide6.Qt3DLogic.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11336 INFO: Analyzing hidden import 'PySide6.QtAsyncio'
11355 INFO: Analyzing hidden import 'PySide6.QtAxContainer'
11361 INFO: Processing standard module hook 'hook-PySide6.QtAxContainer.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11444 INFO: Analyzing hidden import 'PySide6.QtBluetooth'
11477 INFO: Processing standard module hook 'hook-PySide6.QtBluetooth.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11563 INFO: Analyzing hidden import 'PySide6.QtCharts'
11618 INFO: Processing standard module hook 'hook-PySide6.QtCharts.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11712 INFO: Analyzing hidden import 'PySide6.QtConcurrent'
11715 INFO: Processing standard module hook 'hook-PySide6.QtConcurrent.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11796 INFO: Analyzing hidden import 'PySide6.QtDBus'
11814 INFO: Processing standard module hook 'hook-PySide6.QtDBus.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11899 INFO: Analyzing hidden import 'PySide6.QtDataVisualization'
11948 INFO: Processing standard module hook 'hook-PySide6.QtDataVisualization.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12039 INFO: Analyzing hidden import 'PySide6.QtDesigner'
12056 INFO: Processing standard module hook 'hook-PySide6.QtDesigner.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12167 INFO: Analyzing hidden import 'PySide6.QtExampleIcons'
12167 INFO: Analyzing hidden import 'PySide6.QtGraphs'
12235 INFO: Processing standard module hook 'hook-PySide6.QtGraphs.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12353 INFO: Processing standard module hook 'hook-PySide6.QtQml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12851 INFO: Analyzing hidden import 'PySide6.QtGraphsWidgets'
12861 INFO: Processing standard module hook 'hook-PySide6.QtGraphsWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12989 INFO: Processing standard module hook 'hook-PySide6.QtQuick.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13091 INFO: Processing standard module hook 'hook-PySide6.QtQuickWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13178 INFO: Analyzing hidden import 'PySide6.QtHelp'
13188 INFO: Processing standard module hook 'hook-PySide6.QtHelp.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13274 INFO: Analyzing hidden import 'PySide6.QtHttpServer'
13281 INFO: Processing standard module hook 'hook-PySide6.QtHttpServer.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13368 INFO: Analyzing hidden import 'PySide6.QtLocation'
13396 INFO: Processing standard module hook 'hook-PySide6.QtLocation.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13515 INFO: Processing standard module hook 'hook-PySide6.QtPositioning.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13614 INFO: Analyzing hidden import 'PySide6.QtMultimedia'
13654 INFO: Processing standard module hook 'hook-PySide6.QtMultimedia.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13767 INFO: Analyzing hidden import 'PySide6.QtMultimediaWidgets'
13769 INFO: Processing standard module hook 'hook-PySide6.QtMultimediaWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13855 INFO: Analyzing hidden import 'PySide6.QtNetworkAuth'
13868 INFO: Processing standard module hook 'hook-PySide6.QtNetworkAuth.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13955 INFO: Analyzing hidden import 'PySide6.QtNfc'
13979 INFO: Processing standard module hook 'hook-PySide6.QtNfc.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14065 INFO: Analyzing hidden import 'PySide6.QtOpenGLWidgets'
14067 INFO: Processing standard module hook 'hook-PySide6.QtOpenGLWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14154 INFO: Analyzing hidden import 'PySide6.QtPdf'
14162 INFO: Processing standard module hook 'hook-PySide6.QtPdf.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14252 INFO: Analyzing hidden import 'PySide6.QtPdfWidgets'
14255 INFO: Processing standard module hook 'hook-PySide6.QtPdfWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14341 INFO: Analyzing hidden import 'PySide6.QtPrintSupport'
14350 INFO: Processing standard module hook 'hook-PySide6.QtPrintSupport.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14438 INFO: Analyzing hidden import 'PySide6.QtQuick3D'
14445 INFO: Processing standard module hook 'hook-PySide6.QtQuick3D.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14536 INFO: Analyzing hidden import 'PySide6.QtQuickControls2'
14537 INFO: Processing standard module hook 'hook-PySide6.QtQuickControls2.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14621 INFO: Analyzing hidden import 'PySide6.QtQuickTest'
14622 INFO: Analyzing hidden import 'PySide6.QtRemoteObjects'
14632 INFO: Processing standard module hook 'hook-PySide6.QtRemoteObjects.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14718 INFO: Analyzing hidden import 'PySide6.QtScxml'
14728 INFO: Processing standard module hook 'hook-PySide6.QtScxml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14817 INFO: Analyzing hidden import 'PySide6.QtSensors'
14834 INFO: Processing standard module hook 'hook-PySide6.QtSensors.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14927 INFO: Analyzing hidden import 'PySide6.QtSerialBus'
15050 INFO: Analyzing hidden import 'PySide6.QtSerialPort'
15055 INFO: Processing standard module hook 'hook-PySide6.QtSerialPort.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15140 INFO: Analyzing hidden import 'PySide6.QtSpatialAudio'
15147 INFO: Processing standard module hook 'hook-PySide6.QtSpatialAudio.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15233 INFO: Analyzing hidden import 'PySide6.QtSql'
15254 INFO: Processing standard module hook 'hook-PySide6.QtSql.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15359 INFO: Analyzing hidden import 'PySide6.QtStateMachine'
15367 INFO: Processing standard module hook 'hook-PySide6.QtStateMachine.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15452 INFO: Analyzing hidden import 'PySide6.QtSvg'
15456 INFO: Processing standard module hook 'hook-PySide6.QtSvg.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15541 INFO: Analyzing hidden import 'PySide6.QtSvgWidgets'
15543 INFO: Processing standard module hook 'hook-PySide6.QtSvgWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15630 INFO: Analyzing hidden import 'PySide6.QtTest'
15640 INFO: Processing standard module hook 'hook-PySide6.QtTest.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15729 INFO: Analyzing hidden import 'PySide6.QtTextToSpeech'
15734 INFO: Processing standard module hook 'hook-PySide6.QtTextToSpeech.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15831 INFO: Analyzing hidden import 'PySide6.QtUiTools'
15833 INFO: Processing standard module hook 'hook-PySide6.QtUiTools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15921 INFO: Analyzing hidden import 'PySide6.QtWebChannel'
15922 INFO: Processing standard module hook 'hook-PySide6.QtWebChannel.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16009 INFO: Analyzing hidden import 'PySide6.QtWebEngineCore'
16041 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16173 INFO: Analyzing hidden import 'PySide6.QtWebEngineQuick'
16177 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineQuick.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16262 INFO: Analyzing hidden import 'PySide6.QtWebEngineWidgets'
16265 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16351 INFO: Analyzing hidden import 'PySide6.QtWebSockets'
16357 INFO: Processing standard module hook 'hook-PySide6.QtWebSockets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16443 INFO: Analyzing hidden import 'PySide6.QtWebView'
16444 INFO: Analyzing hidden import 'PySide6.QtXml'
16457 INFO: Processing standard module hook 'hook-PySide6.QtXml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16544 INFO: Analyzing hidden import 'PySide6._config'
16544 INFO: Analyzing hidden import 'PySide6._git_pyside_version'
16545 INFO: Analyzing hidden import 'PySide6.scripts'
16545 INFO: Analyzing hidden import 'PySide6.scripts.deploy'
16548 INFO: Analyzing hidden import 'PySide6.scripts.metaobjectdump'
16558 INFO: Analyzing hidden import 'PySide6.scripts.project'
16567 INFO: Analyzing hidden import 'PySide6.scripts.project_lib'
16612 INFO: Processing standard module hook 'hook-xml.etree.cElementTree.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16645 INFO: Analyzing hidden import 'PySide6.scripts.pyside_tool'
16659 INFO: Processing standard module hook 'hook-sysconfig.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16662 INFO: Analyzing hidden import 'PySide6.scripts.qml'
16666 INFO: Analyzing hidden import 'PySide6.scripts.qtpy2cpp'
16668 INFO: Analyzing hidden import 'PySide6.support'
16668 INFO: Analyzing hidden import 'PySide6.support.deprecated'
16669 INFO: Analyzing hidden import 'PySide6.support.generate_pyi'
16671 INFO: Processing module hooks (post-graph stage)...
16786 INFO: Performing binary vs. data reclassification (2766 entries)
16927 INFO: Looking for ctypes DLLs
16931 INFO: Analyzing run-time hooks ...
16932 INFO: Including run-time hook 'pyi_rth_inspect.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
16934 INFO: Including run-time hook 'pyi_rth_pkgutil.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
16935 INFO: Including run-time hook 'pyi_rth_multiprocessing.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
16936 INFO: Including run-time hook 'pyi_rth_cryptography_openssl.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\rthooks'
16937 INFO: Including run-time hook 'pyi_rth_pywintypes.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\rthooks'
16943 INFO: Including run-time hook 'pyi_rth_pythoncom.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\rthooks'
16944 INFO: Including run-time hook 'pyi_rth_pyside6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
16945 INFO: Processing pre-find-module-path hook 'hook-_pyi_rth_utils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_find_module_path'
16946 INFO: Processing standard module hook 'hook-_pyi_rth_utils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16984 INFO: Creating base_library.zip...
17012 INFO: Looking for dynamic libraries
17282 INFO: Extra DLL search directories (AddDllDirectory): ['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\shiboken6']
17282 INFO: Extra DLL search directories (PATH): ['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6']
19494 WARNING: Library not found: could not resolve 'OCI.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqloci.dll'.
19494 WARNING: Library not found: could not resolve 'MIMAPI64.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlmimer.dll'.
19494 WARNING: Library not found: could not resolve 'fbclient.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlibase.dll'.
19494 WARNING: Library not found: could not resolve 'LIBPQ.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlpsql.dll'.
19531 INFO: Warnings written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\warn-plc-agent-tray.txt
19548 INFO: Graph cross-reference written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\xref-plc-agent-tray.html
19593 INFO: checking PYZ
19593 INFO: Building PYZ because PYZ-00.toc is non existent
19593 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz
19910 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz completed successfully.
19918 INFO: checking PKG
19918 INFO: Building PKG because PKG-00.toc is non existent
19918 INFO: Building PKG (CArchive) plc-agent-tray.pkg
19938 INFO: Building PKG (CArchive) plc-agent-tray.pkg completed successfully.
19938 INFO: Bootloader C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\bootloader\Windows-64bit-intel\runw.exe
19938 INFO: checking EXE
19938 INFO: Building EXE because EXE-00.toc is non existent
19938 INFO: Building EXE from EXE-00.toc
19938 INFO: Copying bootloader EXE to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\plc-agent-tray.exe
19941 INFO: Copying icon to EXE
19944 INFO: Copying 0 resources to EXE
19944 INFO: Embedding manifest in EXE
19983 INFO: Appending PKG archive to EXE
20043 INFO: Fixing EXE headers
20399 INFO: Building EXE from EXE-00.toc completed successfully.
20415 INFO: checking COLLECT
20415 INFO: Building COLLECT because COLLECT-00.toc is non existent
20415 INFO: Building COLLECT COLLECT-00.toc
21540 INFO: Building COLLECT COLLECT-00.toc completed successfully.
21573 INFO: Build complete! The results are available in: D:\Apps\plc_logger_app\plc_logger\dist
```

### Command: Remove-Item dist\plc-agent-tray -Recurse -Force -ErrorAction SilentlyContinue (logger fix)
```
(no output)
```

### Command: Remove-Item build\plc-agent-tray -Recurse -Force -ErrorAction SilentlyContinue (logger fix)
```
(no output)
```

### Command: pyinstaller --noconfirm --clean plc-agent-tray.spec (logger fix rebuild)
```
100 INFO: PyInstaller: 6.15.0, contrib hooks: 2025.8
101 INFO: Python: 3.13.3
115 INFO: Platform: Windows-11-10.0.26100-SP0
115 INFO: Python environment: C:\Users\pc\AppData\Local\Programs\Python\Python313
116 INFO: Removing temporary files and cleaning cache in C:\Users\pc\AppData\Local\pyinstaller
121 WARNING: Failed to collect submodules for 'PySide6.scripts.deploy_lib' because importing 'PySide6.scripts.deploy_lib' raised: ModuleNotFoundError: No module named 'project_lib'
359 INFO: Module search paths (PYTHONPATH):
['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\pyinstaller.exe',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\python313.zip',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\DLLs',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\win32\\lib',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\Pythonwin',
 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\setuptools\\_vendor',
 'D:\\Apps\\plc_logger_app\\plc_logger\\apps',
 'D:\\Apps\\plc_logger_app\\plc_logger\\apps\\agent-tray']
544 INFO: checking Analysis
544 INFO: Building Analysis because Analysis-00.toc is non existent
544 INFO: Running Analysis Analysis-00.toc
544 INFO: Target bytecode optimization level: 0
544 INFO: Initializing module dependency graph...
545 INFO: Initializing module graph hook caches...
551 INFO: Analyzing modules for base_library.zip ...
1267 INFO: Processing standard module hook 'hook-encodings.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2401 INFO: Processing standard module hook 'hook-pickle.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
2903 INFO: Processing standard module hook 'hook-heapq.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3160 INFO: Caching module dependency graph...
3179 INFO: Looking for Python shared library...
3182 INFO: Using Python shared library: C:\Users\pc\AppData\Local\Programs\Python\Python313\python313.dll
3182 INFO: Analyzing D:\Apps\plc_logger_app\plc_logger\apps\agent-tray\main.py
3190 INFO: Processing standard module hook 'hook-PySide6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3287 INFO: Processing standard module hook 'hook-shiboken6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3360 INFO: Processing standard module hook 'hook-PySide6.QtNetwork.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
3870 INFO: Processing standard module hook 'hook-PySide6.QtCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4333 INFO: Processing standard module hook 'hook-PySide6.QtGui.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4816 INFO: Processing standard module hook 'hook-PySide6.QtWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
4922 INFO: Processing pre-safe-import-module hook 'hook-win32com.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\pre_safe_import_module'
4951 INFO: Processing standard module hook 'hook-win32com.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
4952 INFO: Processing standard module hook 'hook-pythoncom.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
4990 INFO: Processing standard module hook 'hook-pywintypes.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
5325 INFO: Processing standard module hook 'hook-urllib3.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
5429 INFO: Processing pre-safe-import-module hook 'hook-typing_extensions.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_safe_import_module'
5430 INFO: SetuptoolsInfo: initializing cached setuptools info...
7520 INFO: Processing standard module hook 'hook-multiprocessing.util.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7567 INFO: Processing standard module hook 'hook-xml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
7717 INFO: Processing standard module hook 'hook-_ctypes.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
8282 INFO: Processing standard module hook 'hook-charset_normalizer.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
8361 INFO: Processing standard module hook 'hook-cryptography.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
8857 INFO: hook-cryptography: cryptography does not seem to be using dynamically linked OpenSSL.
9035 INFO: Processing standard module hook 'hook-certifi.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\stdhooks'
9134 INFO: Analyzing hidden import 'PySide6.Qt3DAnimation'
9149 INFO: Processing standard module hook 'hook-PySide6.Qt3DAnimation.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9251 INFO: Processing standard module hook 'hook-PySide6.Qt3DCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
9405 INFO: Processing standard module hook 'hook-PySide6.Qt3DRender.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10245 INFO: Processing standard module hook 'hook-PySide6.QtOpenGL.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10456 INFO: Analyzing hidden import 'PySide6.Qt3DExtras'
10492 INFO: Processing standard module hook 'hook-PySide6.Qt3DExtras.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10580 INFO: Analyzing hidden import 'PySide6.Qt3DInput'
10591 INFO: Processing standard module hook 'hook-PySide6.Qt3DInput.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10678 INFO: Analyzing hidden import 'PySide6.Qt3DLogic'
10679 INFO: Processing standard module hook 'hook-PySide6.Qt3DLogic.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10762 INFO: Analyzing hidden import 'PySide6.QtAsyncio'
10782 INFO: Analyzing hidden import 'PySide6.QtAxContainer'
10789 INFO: Processing standard module hook 'hook-PySide6.QtAxContainer.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10873 INFO: Analyzing hidden import 'PySide6.QtBluetooth'
10907 INFO: Processing standard module hook 'hook-PySide6.QtBluetooth.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
10991 INFO: Analyzing hidden import 'PySide6.QtCharts'
11046 INFO: Processing standard module hook 'hook-PySide6.QtCharts.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11138 INFO: Analyzing hidden import 'PySide6.QtConcurrent'
11141 INFO: Processing standard module hook 'hook-PySide6.QtConcurrent.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11220 INFO: Analyzing hidden import 'PySide6.QtDBus'
11237 INFO: Processing standard module hook 'hook-PySide6.QtDBus.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11323 INFO: Analyzing hidden import 'PySide6.QtDataVisualization'
11373 INFO: Processing standard module hook 'hook-PySide6.QtDataVisualization.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11464 INFO: Analyzing hidden import 'PySide6.QtDesigner'
11481 INFO: Processing standard module hook 'hook-PySide6.QtDesigner.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11591 INFO: Analyzing hidden import 'PySide6.QtExampleIcons'
11591 INFO: Analyzing hidden import 'PySide6.QtGraphs'
11660 INFO: Processing standard module hook 'hook-PySide6.QtGraphs.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
11779 INFO: Processing standard module hook 'hook-PySide6.QtQml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12262 INFO: Analyzing hidden import 'PySide6.QtGraphsWidgets'
12272 INFO: Processing standard module hook 'hook-PySide6.QtGraphsWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12401 INFO: Processing standard module hook 'hook-PySide6.QtQuick.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12502 INFO: Processing standard module hook 'hook-PySide6.QtQuickWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12589 INFO: Analyzing hidden import 'PySide6.QtHelp'
12600 INFO: Processing standard module hook 'hook-PySide6.QtHelp.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12687 INFO: Analyzing hidden import 'PySide6.QtHttpServer'
12695 INFO: Processing standard module hook 'hook-PySide6.QtHttpServer.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12780 INFO: Analyzing hidden import 'PySide6.QtLocation'
12809 INFO: Processing standard module hook 'hook-PySide6.QtLocation.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
12926 INFO: Processing standard module hook 'hook-PySide6.QtPositioning.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13026 INFO: Analyzing hidden import 'PySide6.QtMultimedia'
13066 INFO: Processing standard module hook 'hook-PySide6.QtMultimedia.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13196 INFO: Analyzing hidden import 'PySide6.QtMultimediaWidgets'
13198 INFO: Processing standard module hook 'hook-PySide6.QtMultimediaWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13283 INFO: Analyzing hidden import 'PySide6.QtNetworkAuth'
13296 INFO: Processing standard module hook 'hook-PySide6.QtNetworkAuth.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13381 INFO: Analyzing hidden import 'PySide6.QtNfc'
13391 INFO: Processing standard module hook 'hook-PySide6.QtNfc.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13479 INFO: Analyzing hidden import 'PySide6.QtOpenGLWidgets'
13481 INFO: Processing standard module hook 'hook-PySide6.QtOpenGLWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13567 INFO: Analyzing hidden import 'PySide6.QtPdf'
13576 INFO: Processing standard module hook 'hook-PySide6.QtPdf.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13670 INFO: Analyzing hidden import 'PySide6.QtPdfWidgets'
13673 INFO: Processing standard module hook 'hook-PySide6.QtPdfWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13757 INFO: Analyzing hidden import 'PySide6.QtPrintSupport'
13767 INFO: Processing standard module hook 'hook-PySide6.QtPrintSupport.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13855 INFO: Analyzing hidden import 'PySide6.QtQuick3D'
13862 INFO: Processing standard module hook 'hook-PySide6.QtQuick3D.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
13953 INFO: Analyzing hidden import 'PySide6.QtQuickControls2'
13954 INFO: Processing standard module hook 'hook-PySide6.QtQuickControls2.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14039 INFO: Analyzing hidden import 'PySide6.QtQuickTest'
14039 INFO: Analyzing hidden import 'PySide6.QtRemoteObjects'
14050 INFO: Processing standard module hook 'hook-PySide6.QtRemoteObjects.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14134 INFO: Analyzing hidden import 'PySide6.QtScxml'
14143 INFO: Processing standard module hook 'hook-PySide6.QtScxml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14237 INFO: Analyzing hidden import 'PySide6.QtSensors'
14254 INFO: Processing standard module hook 'hook-PySide6.QtSensors.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14347 INFO: Analyzing hidden import 'PySide6.QtSerialBus'
14367 INFO: Processing standard module hook 'hook-PySide6.QtSerialBus.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14468 INFO: Analyzing hidden import 'PySide6.QtSerialPort'
14473 INFO: Processing standard module hook 'hook-PySide6.QtSerialPort.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14558 INFO: Analyzing hidden import 'PySide6.QtSpatialAudio'
14565 INFO: Processing standard module hook 'hook-PySide6.QtSpatialAudio.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14650 INFO: Analyzing hidden import 'PySide6.QtSql'
14670 INFO: Processing standard module hook 'hook-PySide6.QtSql.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14776 INFO: Analyzing hidden import 'PySide6.QtStateMachine'
14784 INFO: Processing standard module hook 'hook-PySide6.QtStateMachine.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14868 INFO: Analyzing hidden import 'PySide6.QtSvg'
14872 INFO: Processing standard module hook 'hook-PySide6.QtSvg.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
14957 INFO: Analyzing hidden import 'PySide6.QtSvgWidgets'
14959 INFO: Processing standard module hook 'hook-PySide6.QtSvgWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15042 INFO: Analyzing hidden import 'PySide6.QtTest'
15052 INFO: Processing standard module hook 'hook-PySide6.QtTest.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15136 INFO: Analyzing hidden import 'PySide6.QtTextToSpeech'
15141 INFO: Processing standard module hook 'hook-PySide6.QtTextToSpeech.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15235 INFO: Analyzing hidden import 'PySide6.QtUiTools'
15237 INFO: Processing standard module hook 'hook-PySide6.QtUiTools.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15323 INFO: Analyzing hidden import 'PySide6.QtWebChannel'
15324 INFO: Processing standard module hook 'hook-PySide6.QtWebChannel.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15408 INFO: Analyzing hidden import 'PySide6.QtWebEngineCore'
15441 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineCore.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15573 INFO: Analyzing hidden import 'PySide6.QtWebEngineQuick'
15577 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineQuick.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15663 INFO: Analyzing hidden import 'PySide6.QtWebEngineWidgets'
15667 INFO: Processing standard module hook 'hook-PySide6.QtWebEngineWidgets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15750 INFO: Analyzing hidden import 'PySide6.QtWebSockets'
15756 INFO: Processing standard module hook 'hook-PySide6.QtWebSockets.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15839 INFO: Analyzing hidden import 'PySide6.QtWebView'
15840 INFO: Analyzing hidden import 'PySide6.QtXml'
15853 INFO: Processing standard module hook 'hook-PySide6.QtXml.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
15938 INFO: Analyzing hidden import 'PySide6._config'
15939 INFO: Analyzing hidden import 'PySide6._git_pyside_version'
15939 INFO: Analyzing hidden import 'PySide6.scripts'
15939 INFO: Analyzing hidden import 'PySide6.scripts.deploy'
15943 INFO: Analyzing hidden import 'PySide6.scripts.metaobjectdump'
15952 INFO: Analyzing hidden import 'PySide6.scripts.project'
15960 INFO: Analyzing hidden import 'PySide6.scripts.project_lib'
16005 INFO: Processing standard module hook 'hook-xml.etree.cElementTree.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16037 INFO: Analyzing hidden import 'PySide6.scripts.pyside_tool'
16051 INFO: Processing standard module hook 'hook-sysconfig.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16054 INFO: Analyzing hidden import 'PySide6.scripts.qml'
16058 INFO: Analyzing hidden import 'PySide6.scripts.qtpy2cpp'
16060 INFO: Analyzing hidden import 'PySide6.support'
16060 INFO: Analyzing hidden import 'PySide6.support.deprecated'
16061 INFO: Analyzing hidden import 'PySide6.support.generate_pyi'
16063 INFO: Processing module hooks (post-graph stage)...
16126 INFO: Performing binary vs. data reclassification (2766 entries)
16255 INFO: Looking for ctypes DLLs
16259 INFO: Analyzing run-time hooks ...
16260 INFO: Including run-time hook 'pyi_rth_inspect.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
16262 INFO: Including run-time hook 'pyi_rth_pkgutil.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
16263 INFO: Including run-time hook 'pyi_rth_multiprocessing.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
16264 INFO: Including run-time hook 'pyi_rth_cryptography_openssl.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\rthooks'
16264 INFO: Including run-time hook 'pyi_rth_pywintypes.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\rthooks'
16265 INFO: Including run-time hook 'pyi_rth_pythoncom.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\_pyinstaller_hooks_contrib\\rthooks'
16265 INFO: Including run-time hook 'pyi_rth_pyside6.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\rthooks'
16266 INFO: Processing pre-find-module-path hook 'hook-_pyi_rth_utils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks\\pre_find_module_path'
16267 INFO: Processing standard module hook 'hook-_pyi_rth_utils.py' from 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PyInstaller\\hooks'
16305 INFO: Creating base_library.zip...
16331 INFO: Looking for dynamic libraries
16565 INFO: Extra DLL search directories (AddDllDirectory): ['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\shiboken6']
16565 INFO: Extra DLL search directories (PATH): ['C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6']
18685 WARNING: Library not found: could not resolve 'fbclient.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlibase.dll'.
18685 WARNING: Library not found: could not resolve 'OCI.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqloci.dll'.
18685 WARNING: Library not found: could not resolve 'LIBPQ.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlpsql.dll'.
18685 WARNING: Library not found: could not resolve 'MIMAPI64.dll', dependency of 'C:\\Users\\pc\\AppData\\Local\\Programs\\Python\\Python313\\Lib\\site-packages\\PySide6\\plugins\\sqldrivers\\qsqlmimer.dll'.
18723 INFO: Warnings written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\warn-plc-agent-tray.txt
18742 INFO: Graph cross-reference written to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\xref-plc-agent-tray.html
18786 INFO: checking PYZ
18786 INFO: Building PYZ because PYZ-00.toc is non existent
18786 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz
19101 INFO: Building PYZ (ZlibArchive) D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\PYZ-00.pyz completed successfully.
19110 INFO: checking PKG
19110 INFO: Building PKG because PKG-00.toc is non existent
19110 INFO: Building PKG (CArchive) plc-agent-tray.pkg
19129 INFO: Building PKG (CArchive) plc-agent-tray.pkg completed successfully.
19130 INFO: Bootloader C:\Users\pc\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyInstaller\bootloader\Windows-64bit-intel\runw.exe
19130 INFO: checking EXE
19130 INFO: Building EXE because EXE-00.toc is non existent
19130 INFO: Building EXE from EXE-00.toc
19130 INFO: Copying bootloader EXE to D:\Apps\plc_logger_app\plc_logger\build\plc-agent-tray\plc-agent-tray.exe
19134 INFO: Copying icon to EXE
19136 INFO: Copying 0 resources to EXE
19136 INFO: Embedding manifest in EXE
19164 INFO: Appending PKG archive to EXE
19224 INFO: Fixing EXE headers
19588 INFO: Building EXE from EXE-00.toc completed successfully.
19604 INFO: checking COLLECT
19604 INFO: Building COLLECT because COLLECT-00.toc is non existent
19604 INFO: Building COLLECT COLLECT-00.toc
20716 INFO: Building COLLECT COLLECT-00.toc completed successfully.
20749 INFO: Build complete! The results are available in: D:\Apps\plc_logger_app\plc_logger\dist
```

## Step 4 - Front-End Cleanup
### Command: Get-Process plc-logger-tray -ErrorAction SilentlyContinue | Stop-Process -Force
```
No running process
```

### Command: Get-Process | Where-Object { $_.ProcessName -like "PLC*" }
```

ProcessName       Id
-----------       --
plc-agent-core 27272
plc-agent-tray 18912



```

### Command: Remove-Item "C:\Program Files\PLCLogger\ui" -Recurse -Force
```
Removed
```

### Command: Remove-Item "C:\Users\pc\AppData\Local\PLC Logger" -Recurse -Force
```
Removed
```

### Command: Remove-Item "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\PLCLogger" -Recurse -Force
```
Path not found
```

### Command: Remove-Item "C:\Users\pc\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\PLC Logger" -Recurse -Force
```
Path not found
```

### Command: Get-ChildItem "C:\Program Files" -Filter PLCLogger -Directory
```

FullName                  
--------                  
C:\Program Files\PLCLogger



```

### Command: Get-ChildItem "C:\Program Files (x86)" -Filter PLCLogger -Directory
```
No matches
```

### Command: Get-ChildItem (Join-Path $env:LOCALAPPDATA "Programs") -Filter "PLC*" -Directory
```
No matches
```

## Step 5 - Front-End Repository Cleanup
### Command: Remove-Item apps\desktop\dist -Recurse -Force -ErrorAction SilentlyContinue
```
(no output)
```

### Command: Remove-Item apps\desktop\src-tauri\target -Recurse -Force -ErrorAction SilentlyContinue
```
(no output)
```

### Command: Remove-Item apps\desktop\node_modules -Recurse -Force -ErrorAction SilentlyContinue
```
(no output)
```

### Command: Remove-Item apps\desktop\src-tauri\gen -Recurse -Force -ErrorAction SilentlyContinue
```
(no output)
```

### Snapshot: apps\desktop after cleanup
```

Name              Length
----              ------
src                     
src-tauri               
.env              43    
.env.production   202   
index.html        291   
package-lock.json 89776 
package.json      632   
vite.config.js    1327  



```

## Step 6 - Front-End Dependencies
### Command: npm ci (apps/desktop)
```

added 125 packages, and audited 126 packages in 9s

24 packages are looking for funding
  run `npm fund` for details

2 moderate severity vulnerabilities

To address all issues, run:
  npm audit fix

Run `npm audit` for details.
```

### Command: rustup target list --installed
```
x86_64-pc-windows-msvc
```

### Command: npm install -g @tauri-apps/cli
```

changed 2 packages in 4s

1 package is looking for funding
  run `npm fund` for details
```

### Command: cargo check (apps/desktop/src-tauri)
```
   Compiling proc-macro2 v1.0.101
   Compiling unicode-ident v1.0.18
   Compiling cfg-if v1.0.3
   Compiling serde v1.0.219
   Compiling zerocopy v0.8.27
   Compiling windows_x86_64_msvc v0.52.6
   Compiling stable_deref_trait v1.2.0
   Compiling icu_normalizer_data v2.0.0
   Compiling icu_properties_data v2.0.1
   Compiling siphasher v1.0.1
   Compiling autocfg v1.5.0
   Compiling smallvec v1.15.1
   Compiling thiserror v2.0.16
   Compiling siphasher v0.3.11
   Compiling fnv v1.0.7
   Compiling getrandom v0.1.16
   Compiling parking_lot_core v0.9.11
   Compiling typeid v1.0.3
   Compiling writeable v0.6.1
   Compiling itoa v1.0.15
   Compiling strsim v0.11.1
   Compiling memchr v2.7.5
   Compiling ident_case v1.0.1
   Compiling syn v1.0.109
   Compiling litemap v0.8.0
   Compiling thiserror v1.0.69
   Compiling proc-macro-hack v0.5.20+deprecated
   Compiling getrandom v0.3.3
   Compiling scopeguard v1.2.0
   Compiling new_debug_unreachable v1.0.6
   Compiling byteorder v1.5.0
   Compiling getrandom v0.2.16
   Compiling semver v1.0.26
   Compiling anyhow v1.0.99
   Compiling windows-link v0.2.0
   Compiling serde_json v1.0.143
   Compiling phf_shared v0.11.3
   Compiling phf_shared v0.8.0
   Compiling phf_shared v0.10.0
   Compiling windows-sys v0.61.0
   Compiling ryu v1.0.20
   Compiling mac v0.1.1
   Compiling rand_core v0.6.4
   Compiling precomputed-hash v0.1.1
   Compiling winnow v0.7.13
   Compiling utf8_iter v1.0.4
   Compiling toml_writer v1.0.2
   Compiling percent-encoding v2.3.2
   Compiling bitflags v1.3.2
   Compiling utf-8 v0.7.6
   Compiling log v0.4.28
   Compiling futf v0.1.5
   Compiling dtoa v1.0.10
   Compiling unic-common v0.9.0
   Compiling form_urlencoded v1.2.2
   Compiling tendril v0.4.3
   Compiling lock_api v0.4.13
   Compiling indexmap v1.9.3
   Compiling libc v0.2.175
   Compiling nodrop v0.1.14
   Compiling alloc-no-stdlib v2.0.4
   Compiling dtoa-short v0.3.5
   Compiling unic-char-range v0.9.0
   Compiling regex-syntax v0.8.6
   Compiling matches v0.1.10
   Compiling convert_case v0.4.0
   Compiling camino v1.1.12
   Compiling servo_arc v0.2.0
   Compiling aho-corasick v1.1.3
   Compiling alloc-stdlib v0.2.2
   Compiling unic-ucd-version v0.9.0
   Compiling phf v0.8.0
   Compiling fxhash v0.2.1
   Compiling version_check v0.9.5
   Compiling schemars v0.8.22
   Compiling equivalent v1.0.2
   Compiling hashbrown v0.15.5
   Compiling hashbrown v0.12.3
   Compiling bytes v1.10.1
   Compiling windows-targets v0.52.6
   Compiling toml_parser v1.0.2
   Compiling unic-char-property v0.9.0
   Compiling brotli-decompressor v5.0.0
   Compiling find-msvc-tools v0.1.1
   Compiling shlex v1.3.0
    Checking windows-link v0.1.3
   Compiling dyn-clone v1.0.20
   Compiling dunce v1.0.5
   Compiling glob v0.3.3
   Compiling winapi-util v0.1.11
   Compiling rand_core v0.5.1
   Compiling unic-ucd-ident v0.9.0
    Checking windows-strings v0.4.2
    Checking windows-result v0.3.4
   Compiling windows-sys v0.59.0
   Compiling same-file v1.0.6
   Compiling option-ext v0.2.0
   Compiling typenum v1.18.0
   Compiling parking_lot v0.12.4
   Compiling generic-array v0.14.7
   Compiling rand_pcg v0.2.1
   Compiling walkdir v2.5.0
   Compiling dirs-sys v0.5.0
    Checking windows-threading v0.1.0
   Compiling heck v0.5.0
   Compiling cc v1.2.36
   Compiling quote v1.0.40
   Compiling dirs v6.0.0
   Compiling crc32fast v1.5.0
   Compiling simd-adler32 v0.3.7
    Checking raw-window-handle v0.6.2
   Compiling http v1.3.1
   Compiling adler2 v2.0.1
   Compiling indexmap v2.11.1
   Compiling syn v2.0.106
   Compiling time-core v0.1.6
   Compiling crossbeam-utils v0.8.21
    Checking powerfmt v0.2.0
   Compiling num-conv v0.1.0
   Compiling miniz_oxide v0.8.9
   Compiling cookie v0.18.1
   Compiling brotli v8.0.2
   Compiling windows_x86_64_msvc v0.53.0
    Checking deranged v0.5.3
   Compiling time-macros v0.2.24
   Compiling fdeflate v0.3.7
    Checking windows-version v0.1.5
    Checking unicode-segmentation v1.12.0
    Checking once_cell v1.21.3
   Compiling cfg_aliases v0.2.1
   Compiling flate2 v1.1.2
   Compiling softbuffer v0.4.6
   Compiling cpufeatures v0.2.17
   Compiling tauri-runtime v2.8.0
   Compiling wry v0.53.3
    Checking windows-targets v0.53.3
    Checking crossbeam-channel v0.5.15
   Compiling tauri-runtime-wry v2.8.1
   Compiling base64 v0.22.1
   Compiling ppv-lite86 v0.2.21
    Checking lazy_static v1.5.0
    Checking windows-sys v0.60.2
    Checking pin-project-lite v0.2.16
    Checking mime v0.3.17
    Checking tokio v1.47.1
   Compiling rfd v0.15.4
   Compiling regex-automata v0.4.10
   Compiling png v0.17.16
   Compiling vswhom-sys v0.1.3
   Compiling rand_chacha v0.3.1
   Compiling rand_chacha v0.2.2
    Checking time v0.3.43
   Compiling crypto-common v0.1.6
   Compiling block-buffer v0.10.4
   Compiling rand v0.7.3
   Compiling rand v0.8.5
   Compiling digest v0.10.7
   Compiling sha2 v0.10.9
   Compiling ico v0.4.0
   Compiling vswhom v0.1.0
   Compiling winreg v0.55.0
   Compiling phf_generator v0.8.0
   Compiling phf_generator v0.11.3
   Compiling phf_generator v0.10.0
   Compiling phf_codegen v0.8.0
   Compiling phf_codegen v0.11.3
   Compiling string_cache_codegen v0.5.4
   Compiling selectors v0.24.0
    Checking window-vibrancy v0.6.0
   Compiling markup5ever v0.14.1
    Checking regex v1.11.2
   Compiling synstructure v0.13.2
   Compiling darling_core v0.20.11
   Compiling serde_derive_internals v0.29.1
   Compiling cssparser v0.29.6
   Compiling phf_macros v0.10.0
   Compiling serde_derive v1.0.219
   Compiling zerofrom-derive v0.1.6
   Compiling yoke-derive v0.8.0
   Compiling zerovec-derive v0.11.1
   Compiling displaydoc v0.2.5
   Compiling thiserror-impl v2.0.16
   Compiling phf_macros v0.11.3
   Compiling thiserror-impl v1.0.69
   Compiling cssparser-macros v0.6.1
   Compiling ctor v0.2.9
   Compiling derive_more v0.99.20
   Compiling match_token v0.1.0
   Compiling windows-implement v0.60.0
   Compiling windows-interface v0.59.1
   Compiling webview2-com-macros v0.8.0
   Compiling serialize-to-javascript-impl v0.1.2
   Compiling serde_repr v0.1.20
   Compiling schemars_derive v0.8.22
   Compiling phf v0.10.1
   Compiling phf v0.11.3
    Checking windows-core v0.61.2
   Compiling zerofrom v0.1.6
   Compiling yoke v0.8.0
   Compiling webview2-com-sys v0.38.0
   Compiling zerovec v0.11.4
   Compiling zerotrie v0.2.2
    Checking windows-collections v0.2.0
    Checking windows-numerics v0.2.0
    Checking windows-future v0.2.1
   Compiling darling_macro v0.20.11
    Checking windows v0.61.3
   Compiling darling v0.20.11
   Compiling serde_with_macros v3.14.0
    Checking tinystr v0.8.1
    Checking potential_utf v0.1.3
   Compiling icu_collections v2.0.0
   Compiling icu_locale_core v2.0.0
    Checking icu_provider v2.0.0
    Checking dpi v0.1.2
    Checking uuid v1.18.1
    Checking erased-serde v0.4.6
    Checking serde_spanned v1.0.0
    Checking bitflags v2.9.4
    Checking toml_datetime v0.7.0
    Checking serde_with v3.14.0
    Checking toml v0.9.5
   Compiling icu_properties v2.0.1
   Compiling icu_normalizer v2.0.0
    Checking keyboard-types v0.7.0
   Compiling string_cache v0.8.9
   Compiling cargo-platform v0.1.9
    Checking cfb v0.7.3
    Checking serde-untagged v0.1.8
   Compiling rustc_version v0.4.1
    Checking jsonptr v0.6.3
    Checking serialize-to-javascript v0.1.2
   Compiling cargo_metadata v0.19.2
    Checking muda v0.17.1
    Checking infer v0.19.0
    Checking idna_adapter v1.2.1
   Compiling html5ever v0.29.1
    Checking json-patch v3.0.1
    Checking idna v1.1.0
   Compiling embed-resource v3.0.5
   Compiling cargo_toml v0.22.3
   Compiling tauri-winres v0.3.3
    Checking url v2.5.7
    Checking urlpattern v0.3.0
   Compiling kuchikiki v0.8.8-speedreader
    Checking tauri-utils v2.7.0
   Compiling tauri-build v2.4.1
   Compiling tauri-plugin v2.4.0
   Compiling tauri-codegen v2.4.0
   Compiling tauri v2.8.5
   Compiling tauri-plugin-fs v2.4.2
   Compiling tauri-macros v2.4.0
   Compiling tauri-plugin-dialog v2.4.0
   Compiling plc-logger-app v0.1.0 (D:\Apps\plc_logger_app\plc_logger\apps\desktop\src-tauri)
    Checking tao v0.34.3
    Checking webview2-com v0.38.0
error: proc macro panicked
   --> src\main.rs:102:10
    |
102 |     .run(tauri::generate_context!())
    |          ^^^^^^^^^^^^^^^^^^^^^^^^^^
    |
    = help: message: The `frontendDist` configuration is set to `"../dist"` but this path doesn't exist
System.Management.Automation.RemoteException
error: could not compile `plc-logger-app` (bin "plc-logger-app") due to 1 previous error
```

## Step 7 - Front-End Build
### Command: npm run build (apps/desktop)
```

> plc-desktop@0.1.0 build
> set VITE_BASE=./&& vite build

[36mvite v5.4.19 [32mbuilding for production...[36m[39m
transforming...
[32mG£ô[39m 933 modules transformed.
rendering chunks...
[1m[33m[plugin:vite:reporter][39m[22m [33m[plugin vite:reporter] 
(!) D:/Apps/plc_logger_app/plc_logger/apps/desktop/src/lib/api/client.js is dynamically imported by D:/Apps/plc_logger_app/plc_logger/apps/desktop/src/pages/Networking/index.jsx but also statically imported by D:/Apps/plc_logger_app/plc_logger/apps/desktop/src/lib/api/jobs.js, D:/Apps/plc_logger_app/plc_logger/apps/desktop/src/lib/api/mappings.js, D:/Apps/plc_logger_app/plc_logger/apps/desktop/src/lib/api/metrics.js, D:/Apps/plc_logger_app/plc_logger/apps/desktop/src/lib/api/networking.js, D:/Apps/plc_logger_app/plc_logger/apps/desktop/src/lib/api/schemas.js, D:/Apps/plc_logger_app/plc_logger/apps/desktop/src/lib/api/tables.js, D:/Apps/plc_logger_app/plc_logger/apps/desktop/src/pages/LoggingSchedules/index.jsx, dynamic import will not move module into another chunk.
[39m
computing gzip size...
[2mdist/[22m[32mindex.html                     [39m[1m[2m  0.39 kB[22m[1m[22m[2m Göé gzip:   0.26 kB[22m
[2mdist/[22m[35massets/index-CKzN4rIG.css      [39m[1m[2m  6.60 kB[22m[1m[22m[2m Göé gzip:   1.30 kB[22m
[2mdist/[22m[36massets/networking-BJiaLytn.js  [39m[1m[2m  1.58 kB[22m[1m[22m[2m Göé gzip:   0.43 kB[22m
[2mdist/[22m[36massets/core-CyHRNHkm.js        [39m[1m[2m  2.12 kB[22m[1m[22m[2m Göé gzip:   0.91 kB[22m
[2mdist/[22m[36massets/index-DyVrkRgr.js       [39m[1m[2m332.24 kB[22m[1m[22m[2m Göé gzip: 104.06 kB[22m
[32mG£ô built in 1.13s[39m
```

### Command: npm run tauri:build (apps/desktop)
```

> plc-desktop@0.1.0 tauri:build
> tauri build

   Compiling proc-macro2 v1.0.101
   Compiling unicode-ident v1.0.18
   Compiling cfg-if v1.0.3
   Compiling serde v1.0.219
   Compiling zerocopy v0.8.27
   Compiling windows_x86_64_msvc v0.52.6
   Compiling icu_normalizer_data v2.0.0
   Compiling icu_properties_data v2.0.1
   Compiling stable_deref_trait v1.2.0
   Compiling autocfg v1.5.0
   Compiling siphasher v1.0.1
   Compiling thiserror v2.0.16
   Compiling smallvec v1.15.1
   Compiling siphasher v0.3.11
   Compiling parking_lot_core v0.9.11
   Compiling getrandom v0.1.16
   Compiling fnv v1.0.7
   Compiling typeid v1.0.3
   Compiling strsim v0.11.1
   Compiling syn v1.0.109
   Compiling thiserror v1.0.69
   Compiling itoa v1.0.15
   Compiling litemap v0.8.0
   Compiling ident_case v1.0.1
   Compiling memchr v2.7.5
   Compiling writeable v0.6.1
   Compiling getrandom v0.3.3
   Compiling anyhow v1.0.99
   Compiling proc-macro-hack v0.5.20+deprecated
   Compiling windows-link v0.2.0
   Compiling semver v1.0.26
   Compiling getrandom v0.2.16
   Compiling serde_json v1.0.143
   Compiling byteorder v1.5.0
   Compiling new_debug_unreachable v1.0.6
   Compiling scopeguard v1.2.0
   Compiling rand_core v0.6.4
   Compiling phf_shared v0.11.3
   Compiling phf_shared v0.8.0
   Compiling phf_shared v0.10.0
   Compiling windows-sys v0.61.0
   Compiling ryu v1.0.20
   Compiling mac v0.1.1
   Compiling winnow v0.7.13
   Compiling precomputed-hash v0.1.1
   Compiling bitflags v1.3.2
   Compiling dtoa v1.0.10
   Compiling utf-8 v0.7.6
   Compiling libc v0.2.175
   Compiling log v0.4.28
   Compiling utf8_iter v1.0.4
   Compiling toml_writer v1.0.2
   Compiling percent-encoding v2.3.2
   Compiling regex-syntax v0.8.6
   Compiling lock_api v0.4.13
   Compiling futf v0.1.5
   Compiling indexmap v1.9.3
   Compiling windows-targets v0.52.6
   Compiling aho-corasick v1.1.3
   Compiling camino v1.1.12
   Compiling alloc-no-stdlib v2.0.4
   Compiling nodrop v0.1.14
   Compiling convert_case v0.4.0
   Compiling matches v0.1.10
   Compiling unic-common v0.9.0
   Compiling unic-char-range v0.9.0
   Compiling phf v0.8.0
   Compiling dtoa-short v0.3.5
   Compiling fxhash v0.2.1
   Compiling schemars v0.8.22
   Compiling form_urlencoded v1.2.2
   Compiling equivalent v1.0.2
   Compiling hashbrown v0.15.5
   Compiling hashbrown v0.12.3
   Compiling rand_core v0.5.1
   Compiling tendril v0.4.3
   Compiling unic-char-property v0.9.0
   Compiling unic-ucd-version v0.9.0
   Compiling alloc-stdlib v0.2.2
   Compiling servo_arc v0.2.0
   Compiling version_check v0.9.5
   Compiling dyn-clone v1.0.20
   Compiling find-msvc-tools v0.1.1
   Compiling brotli-decompressor v5.0.0
   Compiling unic-ucd-ident v0.9.0
   Compiling windows-link v0.1.3
   Compiling shlex v1.3.0
   Compiling bytes v1.10.1
   Compiling dunce v1.0.5
   Compiling glob v0.3.3
   Compiling rand_pcg v0.2.1
   Compiling windows-result v0.3.4
   Compiling windows-strings v0.4.2
   Compiling windows-sys v0.59.0
   Compiling quote v1.0.40
   Compiling toml_parser v1.0.2
   Compiling option-ext v0.2.0
   Compiling typenum v1.18.0
   Compiling generic-array v0.14.7
   Compiling cc v1.2.36
   Compiling indexmap v2.11.1
   Compiling parking_lot v0.12.4
   Compiling windows-threading v0.1.0
   Compiling syn v2.0.106
   Compiling heck v0.5.0
   Compiling simd-adler32 v0.3.7
   Compiling crc32fast v1.5.0
   Compiling raw-window-handle v0.6.2
   Compiling http v1.3.1
   Compiling winapi-util v0.1.11
   Compiling dirs-sys v0.5.0
   Compiling crossbeam-utils v0.8.21
   Compiling dirs v6.0.0
   Compiling same-file v1.0.6
   Compiling brotli v8.0.2
   Compiling num-conv v0.1.0
   Compiling adler2 v2.0.1
   Compiling time-core v0.1.6
   Compiling walkdir v2.5.0
   Compiling powerfmt v0.2.0
   Compiling miniz_oxide v0.8.9
   Compiling cookie v0.18.1
   Compiling time-macros v0.2.24
   Compiling windows_x86_64_msvc v0.53.0
   Compiling deranged v0.5.3
   Compiling fdeflate v0.3.7
   Compiling windows-version v0.1.5
   Compiling ppv-lite86 v0.2.21
   Compiling flate2 v1.1.2
   Compiling regex-automata v0.4.10
   Compiling once_cell v1.21.3
   Compiling unicode-segmentation v1.12.0
   Compiling cfg_aliases v0.2.1
   Compiling crossbeam-channel v0.5.15
   Compiling softbuffer v0.4.6
   Compiling rand_chacha v0.3.1
   Compiling rand_chacha v0.2.2
   Compiling png v0.17.16
   Compiling vswhom-sys v0.1.3
   Compiling tauri-runtime v2.8.0
   Compiling wry v0.53.3
   Compiling cpufeatures v0.2.17
   Compiling rand v0.8.5
   Compiling rand v0.7.3
   Compiling block-buffer v0.10.4
   Compiling crypto-common v0.1.6
   Compiling digest v0.10.7
   Compiling windows-targets v0.53.3
   Compiling base64 v0.22.1
   Compiling lazy_static v1.5.0
   Compiling tauri-runtime-wry v2.8.1
   Compiling windows-sys v0.60.2
   Compiling time v0.3.43
   Compiling pin-project-lite v0.2.16
   Compiling ico v0.4.0
   Compiling sha2 v0.10.9
   Compiling phf_generator v0.11.3
   Compiling phf_generator v0.10.0
   Compiling phf_generator v0.8.0
   Compiling phf_codegen v0.8.0
   Compiling tokio v1.47.1
   Compiling phf_codegen v0.11.3
   Compiling string_cache_codegen v0.5.4
   Compiling mime v0.3.17
   Compiling rfd v0.15.4
   Compiling selectors v0.24.0
   Compiling vswhom v0.1.0
   Compiling markup5ever v0.14.1
   Compiling winreg v0.55.0
   Compiling regex v1.11.2
   Compiling synstructure v0.13.2
   Compiling darling_core v0.20.11
   Compiling serde_derive_internals v0.29.1
   Compiling window-vibrancy v0.6.0
   Compiling phf_macros v0.10.0
   Compiling cssparser v0.29.6
   Compiling serde_derive v1.0.219
   Compiling zerofrom-derive v0.1.6
   Compiling yoke-derive v0.8.0
   Compiling zerovec-derive v0.11.1
   Compiling displaydoc v0.2.5
   Compiling thiserror-impl v2.0.16
   Compiling phf_macros v0.11.3
   Compiling thiserror-impl v1.0.69
   Compiling cssparser-macros v0.6.1
   Compiling ctor v0.2.9
   Compiling match_token v0.1.0
   Compiling derive_more v0.99.20
   Compiling schemars_derive v0.8.22
   Compiling windows-interface v0.59.1
   Compiling windows-implement v0.60.0
   Compiling webview2-com-macros v0.8.0
   Compiling serialize-to-javascript-impl v0.1.2
   Compiling serde_repr v0.1.20
   Compiling phf v0.11.3
   Compiling phf v0.10.1
   Compiling windows-core v0.61.2
   Compiling zerofrom v0.1.6
   Compiling yoke v0.8.0
   Compiling darling_macro v0.20.11
   Compiling webview2-com-sys v0.38.0
   Compiling windows-numerics v0.2.0
   Compiling zerovec v0.11.4
   Compiling zerotrie v0.2.2
   Compiling windows-future v0.2.1
   Compiling windows-collections v0.2.0
   Compiling darling v0.20.11
   Compiling serde_with_macros v3.14.0
   Compiling windows v0.61.3
   Compiling tinystr v0.8.1
   Compiling potential_utf v0.1.3
   Compiling icu_collections v2.0.0
   Compiling icu_locale_core v2.0.0
   Compiling icu_provider v2.0.0
   Compiling icu_normalizer v2.0.0
   Compiling icu_properties v2.0.1
   Compiling idna_adapter v1.2.1
   Compiling idna v1.1.0
   Compiling serde_spanned v1.0.0
   Compiling toml_datetime v0.7.0
   Compiling string_cache v0.8.9
   Compiling uuid v1.18.1
   Compiling url v2.5.7
   Compiling erased-serde v0.4.6
   Compiling cargo-platform v0.1.9
   Compiling serde_with v3.14.0
   Compiling toml v0.9.5
   Compiling rustc_version v0.4.1
   Compiling cfb v0.7.3
   Compiling dpi v0.1.2
   Compiling bitflags v2.9.4
   Compiling serde-untagged v0.1.8
   Compiling keyboard-types v0.7.0
   Compiling urlpattern v0.3.0
   Compiling infer v0.19.0
   Compiling jsonptr v0.6.3
   Compiling cargo_metadata v0.19.2
   Compiling html5ever v0.29.1
   Compiling embed-resource v3.0.5
   Compiling cargo_toml v0.22.3
   Compiling tauri-winres v0.3.3
   Compiling json-patch v3.0.1
   Compiling serialize-to-javascript v0.1.2
   Compiling muda v0.17.1
   Compiling kuchikiki v0.8.8-speedreader
   Compiling tauri-utils v2.7.0
   Compiling tauri-build v2.4.1
   Compiling tauri-plugin v2.4.0
   Compiling tauri-codegen v2.4.0
   Compiling tauri v2.8.5
   Compiling tauri-plugin-fs v2.4.2
   Compiling tauri-macros v2.4.0
   Compiling tauri-plugin-dialog v2.4.0
   Compiling plc-logger-app v0.1.0 (D:\Apps\plc_logger_app\plc_logger\apps\desktop\src-tauri)
   Compiling tao v0.34.3
   Compiling webview2-com v0.38.0
    Finished `release` profile [optimized] target(s) in 52.08s
       Built application at: D:\Apps\plc_logger_app\plc_logger\apps\desktop\src-tauri\target\release\plc-logger-app.exe
        Info Target: x64
     Running makensis.exe to produce D:\Apps\plc_logger_app\plc_logger\apps\desktop\src-tauri\target\release\bundle\nsis\PLC Logger_0.1.0_x64-setup.exe
    Finished 1 bundle at:
        D:\Apps\plc_logger_app\plc_logger\apps\desktop\src-tauri\target\release\bundle\nsis\PLC Logger_0.1.0_x64-setup.exe
System.Management.Automation.RemoteException
```

