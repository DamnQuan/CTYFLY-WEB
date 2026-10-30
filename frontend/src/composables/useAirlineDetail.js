import { computed, ref } from 'vue';
import { api } from '../api.js';

/**
 * 航司详情页的公共状态与身份判断。
 * 只负责「这家航司是什么、我和它是什么关系」，不负责各页签的业务动作。
 */
export function useAirlineDetail(airlineId) {
  const data = ref(null);
  const loading = ref(true);
  const error = ref('');
  const joinLoading = ref(false);

  const airline = computed(() => data.value?.airline);
  const isCeo = computed(() => data.value?.is_ceo);
  const myMembership = computed(() => data.value?.my_membership);
  // 管理权限：CEO 或 CEO 任命的部长，对应后端 _require_manager 口径
  const canManage = computed(
    () => isCeo.value || (myMembership.value?.role !== 'ceo' && !!myMembership.value?.minister),
  );
  const isMember = computed(
    () => myMembership.value
      && myMembership.value.airline_id === airlineId.value
      && myMembership.value.status === 'active',
  );
  const pendingJoin = computed(
    () => myMembership.value
      && myMembership.value.airline_id === airlineId.value
      && myMembership.value.status === 'pending',
  );
  // 我在别家航司，可以发起跳槽
  const inOtherAirline = computed(
    () => myMembership.value
      && myMembership.value.airline_id !== airlineId.value
      && myMembership.value.status === 'active',
  );
  // 管理中心概览：后端仅向 CEO 返回 applications，部长侧为空列表
  const pendingMembers = computed(() => (data.value?.applications || []).length);

  async function fetchDetail() {
    loading.value = true;
    error.value = '';
    try {
      const detail = await api.get(`/api/airlines/${airlineId.value}`);
      data.value = detail;
      return detail;
    } catch (err) {
      error.value = err.message;
      return null;
    } finally {
      loading.value = false;
    }
  }

  return {
    data,
    loading,
    error,
    joinLoading,
    airline,
    isCeo,
    myMembership,
    canManage,
    isMember,
    pendingJoin,
    inOtherAirline,
    pendingMembers,
    fetchDetail,
  };
}
