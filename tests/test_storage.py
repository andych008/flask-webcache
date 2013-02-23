import unittest
from datetime import timedelta, datetime
from cPickle import dumps, loads

from flask import Flask
from werkzeug.wrappers import Response
from werkzeug.datastructures import HeaderSet
from werkzeug.contrib.cache import SimpleCache
from flask_webcache.storage import Config, Metadata, Store, Retrieval, CacheMiss

a = Flask(__name__)

class UtilsTestCase(unittest.TestCase):

    def test_config_kwargs(self):
        with self.assertRaises(TypeError):
            Config(foo=1)

    def test_metadata(self):
        def check_metadata(m):
            self.assertEquals(m.salt, 'qux')
            self.assertIn('foo', m.vary)
            self.assertIn('bar', m.vary)
        m = Metadata(HeaderSet(('foo', 'bar')), 'qux')
        check_metadata(m)
        check_metadata(loads(dumps(m)))

class StorageTestCase(unittest.TestCase):

    def setUp(self):
        self.c = SimpleCache()
        self.s = Store(self.c)
        self.r = Retrieval(self.c)

    def test_basic_cachability(self):
        with a.test_request_context('/foo'):
            self.assertFalse(self.s.should_cache_response(Response(x for x in 'foo')))
            self.assertFalse(self.s.should_cache_response(Response(status=500)))
            self.assertTrue(self.s.should_cache_response(Response('foo')))
            self.assertTrue(self.s.should_cache_response(Response()))
            r = Response()
            r.vary.add('*')
            self.assertFalse(self.s.should_cache_response(r))
        with a.test_request_context('/foo', method='POST'):
            self.assertFalse(self.s.should_cache_response(Response('foo')))

    def test_cache_control_cachability(self):
        def check_response_with_cache_control(**cc):
            r = Response()
            for k, v in cc.iteritems():
                setattr(r.cache_control, k, v)
            return self.s.should_cache_response(r)
        with a.test_request_context():
            self.assertTrue(check_response_with_cache_control(max_age=10))
            self.assertFalse(check_response_with_cache_control(max_age=0))
            self.assertFalse(check_response_with_cache_control(private=True))
            self.assertFalse(check_response_with_cache_control(no_cache=True))
            self.assertFalse(check_response_with_cache_control(no_store=True))

    def test_expire_cachability(self):
        def check_response_with_expires(dt):
            r = Response()
            r.expires = dt
            return self.s.should_cache_response(r)
        with a.test_request_context():
            self.assertFalse(check_response_with_expires(datetime.now() - timedelta(seconds=1)))
            self.assertTrue(check_response_with_expires(datetime.now() + timedelta(seconds=1)))

    def test_default_cachability(self):
        with a.test_request_context('/foo'):
            self.assertTrue(self.s.should_cache_response(Response()))
        with a.test_request_context('/foo', query_string='?bar'):
            self.assertFalse(self.s.should_cache_response(Response()))

    def test_x_cache_headers(self):
        r = Response()
        self.s.mark_cache_hit(r)
        self.assertEquals(r.headers[self.s.X_CACHE_HEADER], 'hit')
        self.s.mark_cache_miss(r)
        self.assertEquals(r.headers[self.s.X_CACHE_HEADER], 'miss')

    def test_metadata_miss(self):
        with self.assertRaises(CacheMiss):
            with a.test_request_context('/foo'):
                self.r.fetch_metadata()

    def test_response_miss(self):
        with self.assertRaises(CacheMiss):
            with a.test_request_context('/foo'):
                self.r.fetch_response()

    def test_store_retrieve_cycle(self):
        with a.test_request_context('/foo'):
            r = Response('foo')
            self.s.cache_response(r)
            self.assertEquals(len(self.c._cache), 2)
            r2 = self.r.fetch_response()
            self.assertEquals(r.data, r2.data)

    def test_vary_miss(self):
        with a.test_request_context('/foo', headers=(('accept-encoding', 'gzip'),)):
            r = Response('foo')
            r.vary.add('accept-encoding')
            r.content_encoding = 'gzip'
            self.s.cache_response(r)
        with self.assertRaises(CacheMiss):
            with a.test_request_context('/foo'):
                self.r.fetch_response()

    def test_invalidation_condition(self):
        with a.test_request_context('/foo', method="PUT"):
            r = Response('foo')
            self.assertTrue(self.s.should_invalidate_resource(r))
            r = Response('foo', status=500)
            self.assertFalse(self.s.should_invalidate_resource(r))
        with a.test_request_context('/foo'):
            r = Response('foo')
            self.assertFalse(self.s.should_invalidate_resource(r))

    def test_invalidation(self):
        with a.test_request_context('/foo'):
            r = Response('foo')
            self.s.cache_response(r)
            self.assertEquals(len(self.c._cache), 2)
        with a.test_request_context('/foo', method="PUT"):
            r = Response('foo')
            self.assertTrue(self.s.should_invalidate_resource(r))
            self.s.invalidate_resource()
            self.assertEquals(len(self.c._cache), 1)
        with self.assertRaises(CacheMiss):
            with a.test_request_context('/foo'):
                self.r.fetch_response()

    def test_master_salt_invalidation(self):
        with a.test_request_context('/foo'):
            r = Response('foo')
            self.s.cache_response(r)
            self.assertEquals(self.r.fetch_response().data, 'foo')
            self.r.config.master_salt = 'newsalt'
            with self.assertRaises(CacheMiss):
                self.r.fetch_response()
