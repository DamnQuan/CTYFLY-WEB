import { describe, expect, it } from 'vitest';
import {
  APP_STATUS,
  EVENT_STATUS,
  TICKET_STATUS,
  avatarUrl,
  fmtTime,
  localDate,
  localMonth,
  safeHttpUrl,
} from './utils.js';

describe('fmtTime', () => {
  it('把 ISO 时间转成可读的分钟精度', () => {
    expect(fmtTime('2026-10-24T18:05:33')).toBe('2026-10-24 18:05');
  });

  it('空值返回空串', () => {
    expect(fmtTime('')).toBe('');
    expect(fmtTime(null)).toBe('');
  });
});

describe('localDate 与 localMonth', () => {
  it('日期按本地时区补零', () => {
    expect(localDate(new Date(2026, 0, 5))).toBe('2026-01-05');
  });

  it('月份按本地时区补零', () => {
    expect(localMonth(new Date(2026, 9, 24))).toBe('2026-10');
  });
});

describe('safeHttpUrl', () => {
  it('允许 https 与 http', () => {
    expect(safeHttpUrl('https://ccflysim.cn/docs')).toBe('https://ccflysim.cn/docs');
    expect(safeHttpUrl('http://example.com')).toBe('http://example.com');
  });

  it('拒绝 javascript 伪协议', () => {
    expect(safeHttpUrl('javascript:alert(1)')).toBe('');
  });

  it('拒绝 data 伪协议', () => {
    expect(safeHttpUrl('data:text/html,<script>alert(1)</script>')).toBe('');
  });

  it('拒绝非法地址与非字符串', () => {
    expect(safeHttpUrl('not a url')).toBe('');
    expect(safeHttpUrl(null)).toBe('');
  });
});

describe('avatarUrl', () => {
  it('优先使用用户头像', () => {
    expect(avatarUrl({ username: 'admin', avatar_url: '/uploads/a.png' })).toBe('/uploads/a.png');
  });

  it('没有头像时生成首字母 SVG', () => {
    const url = avatarUrl({ username: 'captain' });
    expect(url.startsWith('data:image/svg+xml')).toBe(true);
    expect(url).toContain('C');
  });
});

describe('状态字典', () => {
  it('事件、申请、工单三套状态都覆盖关键枚举', () => {
    expect(Object.keys(EVENT_STATUS)).toEqual(['upcoming', 'ongoing', 'ended', 'cancelled']);
    expect(Object.keys(APP_STATUS)).toEqual(['pending', 'approved', 'rejected']);
    expect(Object.keys(TICKET_STATUS)).toEqual(['open', 'replied', 'closed']);
  });
});
