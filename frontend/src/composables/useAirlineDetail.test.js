import { describe, expect, it } from 'vitest';
import { ref } from 'vue';
import { useAirlineDetail } from './useAirlineDetail.js';

describe('useAirlineDetail 的身份判断', () => {
  function buildDetail(data, id = 7) {
    const detail = useAirlineDetail(ref(id));
    detail.data.value = data;
    return detail;
  }

  it('普通成员不是管理者', () => {
    const detail = buildDetail({
      my_membership: { airline_id: 7, status: 'active', role: 'pilot' },
    });
    expect(detail.isMember.value).toBe(true);
    expect(detail.isCeo.value).toBeFalsy();
    expect(detail.canManage.value).toBe(false);
  });

  it('CEO 是管理者', () => {
    const detail = buildDetail({
      is_ceo: true,
      my_membership: { airline_id: 7, status: 'active', role: 'ceo' },
    });
    expect(detail.isCeo.value).toBe(true);
    expect(detail.canManage.value).toBe(true);
  });

  it('被任命的部长是管理者', () => {
    const detail = buildDetail({
      my_membership: { airline_id: 7, status: 'active', role: 'pilot', minister: true },
    });
    expect(detail.canManage.value).toBe(true);
  });

  it('别家航司的成员不算本航司成员', () => {
    const detail = buildDetail({
      my_membership: { airline_id: 8, status: 'active', role: 'pilot' },
    });
    expect(detail.isMember.value).toBeFalsy();
    expect(detail.inOtherAirline.value).toBe(true);
  });

  it('待审批申请走 pendingJoin', () => {
    const detail = buildDetail({
      my_membership: { airline_id: 7, status: 'pending', role: '' },
    });
    expect(detail.pendingJoin.value).toBe(true);
    expect(detail.isMember.value).toBeFalsy();
  });

  it('待审批成员数来自 applications', () => {
    const detail = buildDetail({ applications: [{ id: 1 }, { id: 2 }], members: [], routes: [] });
    expect(detail.pendingMembers.value).toBe(2);
  });
});
