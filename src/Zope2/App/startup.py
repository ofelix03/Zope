##############################################################################
#
# Copyright (c) 2002 Zope Foundation and Contributors.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Initialize the Zope2 Package and provide a published module
"""

import imp
import sys
from time import asctime

import AccessControl.User
from AccessControl.SecurityManagement import newSecurityManager
from AccessControl.SecurityManagement import noSecurityManager
import ZODB
from zope.deferredimport import deprecated
from zope.event import notify
from zope.processlifetime import DatabaseOpened
from zope.processlifetime import DatabaseOpenedWithRoot

from App.config import getConfiguration
import App.ZApplication
import OFS.Application
import Zope2

# BBB Zope 5.0
deprecated(
    'Please import from ZServer.ZPublisher.exceptionhook.',
    RequestContainer='ZServer.ZPublisher.exceptionhook:RequestContainer',
    zpublisher_exception_hook=(
        'ZServer.ZPublisher.exceptionhook:EXCEPTION_HOOK'),
    ZPublisherExceptionHook='ZServer.ZPublisher.exceptionhook:ExceptionHook',
)

deprecated(
    'Please import from ZPublisher.WSGIPublisher.',
    validated_hook='ZPublisher.WSGIPublisher:validate_user',
)

app = None
startup_time = asctime()
_patched = False


def load_zcml():
    # This hook is overriden by ZopeTestCase
    from .zcml import load_site
    load_site()

    # Set up Zope2 specific vocabulary registry
    from .schema import configure_vocabulary_registry
    configure_vocabulary_registry()


def patch_persistent():
    global _patched
    if _patched:
        return
    _patched = True

    from Persistence import Persistent
    from AccessControl.class_init import InitializeClass
    Persistent.__class_init__ = InitializeClass


def startup():
    patch_persistent()

    global app

    # Import products
    OFS.Application.import_products()

    configuration = getConfiguration()

    # Open the database
    dbtab = configuration.dbtab
    try:
        # Try to use custom storage
        try:
            m = imp.find_module('custom_zodb', [configuration.testinghome])
        except Exception:
            m = imp.find_module('custom_zodb', [configuration.instancehome])
    except Exception:
        # if there is no custom_zodb, use the config file specified databases
        DB = dbtab.getDatabase('/', is_root=1)
    else:
        m = imp.load_module('Zope2.custom_zodb', m[0], m[1], m[2])
        sys.modules['Zope2.custom_zodb'] = m

        # Get the database and join it to the dbtab multidatabase
        # FIXME: this uses internal datastructures of dbtab
        databases = getattr(dbtab, 'databases', {})
        if hasattr(m, 'DB'):
            DB = m.DB
            databases.update(getattr(DB, 'databases', {}))
            DB.databases = databases
        else:
            DB = ZODB.DB(m.Storage, databases=databases)

    # Force a connection to every configured database, to ensure all of them
    # can indeed be opened. This avoids surprises during runtime when traversal
    # to some database mountpoint fails as the underlying storage cannot be
    # opened at all
    if dbtab is not None:
        for mount, name in dbtab.listMountPaths():
            _db = dbtab.getDatabase(mount)
            _conn = _db.open()
            _conn.close()
            del _conn
            del _db

    notify(DatabaseOpened(DB))

    Zope2.DB = DB
    Zope2.opened.append(DB)

    from . import ClassFactory
    DB.classFactory = ClassFactory.ClassFactory

    # "Log on" as system user
    newSecurityManager(None, AccessControl.User.system)

    # Set up the CA
    load_zcml()

    # Set up the "app" object that automagically opens
    # connections
    app = App.ZApplication.ZApplicationWrapper(
        DB, 'Application', OFS.Application.Application)
    Zope2.bobo_application = app

    # Initialize the app object
    application = app()
    OFS.Application.initialize(application)
    application._p_jar.close()

    # "Log off" as system user
    noSecurityManager()

    global startup_time
    startup_time = asctime()

    notify(DatabaseOpenedWithRoot(DB))
