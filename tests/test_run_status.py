"""Scoped run observations expose lease timing, never frozen operational inputs."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from apps.api.db import Job, Organization, User
from apps.api.main import create_app
from apps.api.security import password_hash
from database_fixture import isolated_database_url


class RunStatusTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ, {'ASBOLJAM_ENV':'local','COOKIE_SECURE':'false',
                                   'ALLOWED_ORIGINS':'http://localhost:3000'})
        env.start();self.addCleanup(env.stop)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.app=create_app(isolated_database_url('sqlite:///'+(Path(temp.name)/'db.sqlite').as_posix()))
        self.addCleanup(self.app.state.engine.dispose)
        self.factory=self.app.state.sessions
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        with self.factory() as db:
            for org in ['A','B']:
                db.add(Organization(id=org,name=org,timezone='Asia/Qyzylorda',data_policy='synthetic_only',provenance='test_fixture'))
            db.add(User(id='actor',organization_id='A',email='status@fixture.invalid',
                        password_hash=password_hash('Fixture-status-password-42!'),role='analyst',branch_ids=['1']))
            for identifier,org,branch in [('visible','A','1'),('branch','A','2'),('tenant','B','1')]:
                db.add(Job(id=identifier,organization_id=org,branch_id=branch,actor_id='actor',kind='forecast',
                           payload={'private':'private-payload'},snapshot={'private':'private-snapshot'}))
            db.commit()

    def login(self):
        response=self.client.post('/api/v1/session/login',headers={'Origin':'http://localhost:3000'},
            json={'email':'status@fixture.invalid','password':'Fixture-status-password-42!'})
        self.assertEqual(response.status_code,200)

    def test_queued_metadata_is_nullable_no_store_and_input_snapshot_is_private(self):
        self.login()
        before=time.time();response=self.client.get('/api/v1/runs/visible');after=time.time()
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertEqual(data['status'],'queued')
        self.assertIsNone(data['started_at']);self.assertIsNone(data['heartbeat_at'])
        self.assertIsNone(data['finished_at']);self.assertIsNone(data['result_id'])
        self.assertLessEqual(before,data['observed_at']);self.assertLessEqual(data['observed_at'],after)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertNotIn('private',response.text)
        self.assertNotIn('actor_id',data);self.assertNotIn('snapshot',data);self.assertNotIn('payload',data)

    def test_running_heartbeat_and_completed_timestamps_are_facts_not_percentages(self):
        self.login()
        with self.factory() as db:
            row=db.get(Job,'visible');row.status='running';row.started_at=100;row.heartbeat_at=200;db.commit()
        data=self.client.get('/api/v1/runs/visible').json()
        self.assertEqual((data['started_at'],data['heartbeat_at']),(100,200))
        self.assertNotIn('progress',data)
        with self.factory() as db:
            row=db.get(Job,'visible');row.status='succeeded';row.result_id='result';row.finished_at='2026-01-01T01:00:00Z';db.commit()
        data=self.client.get('/api/v1/runs/visible').json()
        self.assertEqual((data['status'],data['result_id'],data['finished_at']),('succeeded','result','2026-01-01T01:00:00Z'))

    def test_status_keeps_authentication_role_and_both_scope_fences(self):
        self.assertEqual(self.client.get('/api/v1/runs/visible').status_code,401)
        self.login()
        for identifier in ['branch','tenant','missing']:
            self.assertEqual(self.client.get('/api/v1/runs/'+identifier).status_code,404)
        with self.factory() as db:
            db.get(User,'actor').role='warehouse';db.commit()
        self.assertEqual(self.client.get('/api/v1/runs/visible').status_code,403)

    def test_openapi_describes_timing_and_does_not_advertise_private_inputs(self):
        schema=self.app.openapi()
        properties=schema['components']['schemas']['RunResponse']['properties']
        self.assertTrue({'started_at','heartbeat_at','observed_at'}.issubset(properties))
        self.assertFalse({'payload','snapshot','actor_id'}.intersection(properties))


if __name__=='__main__':
    unittest.main()
