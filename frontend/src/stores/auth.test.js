import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAuthStore } from './auth.js';

describe('auth store 的登录态与能力判断', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it('没有用户时未登录', () => {
    const store = useAuthStore();
    expect(store.isLoggedIn).toBe(false);
    expect(store.isAdmin).toBe(false);
    expect(store.isStaff).toBe(false);
  });

  it('admin 角色拥有管理员与工作人员身份', () => {
    const store = useAuthStore();
    store.user = { username: 'admin', role: 'admin', capabilities: [] };
    expect(store.isLoggedIn).toBe(true);
    expect(store.isAdmin).toBe(true);
    expect(store.isStaff).toBe(true);
  });

  it('sup 角色算工作人员但不算管理员', () => {
    const store = useAuthStore();
    store.user = { username: 'sup', role: 'sup', capabilities: ['view_surveys'] };
    expect(store.isStaff).toBe(true);
    expect(store.isAdmin).toBe(false);
  });

  it('admin 对任意能力都放行', () => {
    const store = useAuthStore();
    store.user = { username: 'admin', role: 'admin', capabilities: [] };
    expect(store.can('view_surveys')).toBe(true);
    expect(store.can('不存在的权限')).toBe(true);
  });

  it('普通用户只拥有后端下发的能力', () => {
    const store = useAuthStore();
    store.user = { username: 'user', role: 'user', capabilities: ['view_surveys'] };
    expect(store.can('view_surveys')).toBe(true);
    expect(store.can('manage_users')).toBe(false);
  });

  it('能力列表缺失时按空数组处理', () => {
    const store = useAuthStore();
    store.user = { username: 'user', role: 'user' };
    expect(store.capabilities).toEqual([]);
    expect(store.can('view_surveys')).toBe(false);
    expect(store.canAdmin).toBe(false);
  });

  it('拥有任意后台能力的用户可进入管理后台', () => {
    const store = useAuthStore();
    store.user = { username: 'staff', role: 'user', capabilities: ['manage_notices'] };
    expect(store.canAdmin).toBe(true);
  });

  it('admin 恒可进入管理后台', () => {
    const store = useAuthStore();
    store.user = { username: 'admin', role: 'admin', capabilities: [] };
    expect(store.canAdmin).toBe(true);
  });
});
