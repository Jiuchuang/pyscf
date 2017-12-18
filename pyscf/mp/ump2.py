'''
UMP2 with spatial integals
'''

import time
import numpy
from pyscf import lib
from pyscf import gto
from pyscf import ao2mo
from pyscf.lib import logger
from pyscf.mp import mp2
from pyscf.ao2mo import _ao2mo

# This is unrestricted (U)MP2, i.e. spin-orbital form.

def kernel(mp, mo_energy=None, mo_coeff=None, eris=None, with_t2=True,
           verbose=logger.NOTE):
    if mo_energy is None or mo_coeff is None:
        moidx = mp.get_frozen_mask()
        mo_coeff = None
        mo_energy = (mp.mo_energy[0][moidx[0]], mp.mo_energy[1][moidx[1]])
    else:
        # For backward compatibility.  In pyscf-1.4 or earlier, mp.frozen is
        # not supported when mo_energy or mo_coeff is given.
        assert(mp.frozen is 0 or mp.frozen is None)

    if eris is None: eris = mp.ao2mo(mo_coeff)

    nocca, noccb = mp.get_nocc()
    nmoa, nmob = mp.get_nmo()
    nvira, nvirb = nmoa-nocca, nmob-noccb
    mo_ea, mo_eb = mo_energy
    eia_a = mo_ea[:nocca,None] - mo_ea[None,nocca:]
    eia_b = mo_eb[:noccb,None] - mo_eb[None,noccb:]

    if with_t2:
        dtype = eris.ovov.dtype
        t2aa = numpy.empty((nocca,nocca,nvira,nvira), dtype=dtype)
        t2ab = numpy.empty((nocca,noccb,nvira,nvirb), dtype=dtype)
        t2bb = numpy.empty((noccb,noccb,nvirb,nvirb), dtype=dtype)
        t2 = (t2aa,t2ab,t2bb)
    else:
        t2 = None

    emp2 = 0.0
    for i in range(nocca):
        eris_ovov = numpy.asarray(eris.ovov[i*nvira:(i+1)*nvira])
        eris_ovov = eris_ovov.reshape(nvira,nocca,nvira).transpose(1,0,2)
        t2i = eris_ovov.conj()/lib.direct_sum('a+jb->jab', eia_a[i], eia_a)
        emp2 += numpy.einsum('jab,jab', t2i, eris_ovov) * .5
        emp2 -= numpy.einsum('jab,jba', t2i, eris_ovov) * .5
        if with_t2:
            t2aa[i] = t2i - t2i.transpose(0,2,1)

        eris_ovov = numpy.asarray(eris.ovOV[i*nvira:(i+1)*nvira])
        eris_ovov = eris_ovov.reshape(nvira,noccb,nvirb).transpose(1,0,2)
        t2i = eris_ovov.conj()/lib.direct_sum('a+jb->jab', eia_a[i], eia_b)
        emp2 += numpy.einsum('JaB,JaB', t2i, eris_ovov)
        if with_t2:
            t2ab[i] = t2i

    for i in range(noccb):
        eris_ovov = numpy.asarray(eris.OVOV[i*nvirb:(i+1)*nvirb])
        eris_ovov = eris_ovov.reshape(nvirb,noccb,nvirb).transpose(1,0,2)
        t2i = eris_ovov.conj()/lib.direct_sum('a+jb->jab', eia_b[i], eia_b)
        emp2 += numpy.einsum('jab,jab', t2i, eris_ovov) * .5
        emp2 -= numpy.einsum('jab,jba', t2i, eris_ovov) * .5
        if with_t2:
            t2bb[i] = t2i - t2i.transpose(0,2,1)

    return emp2.real, t2


def get_nocc(mp):
    if mp._nocc is not None:
        return mp._nocc
    if isinstance(mp.frozen, (int, numpy.integer)):
        nocca = int(mp.mo_occ[0].sum()) - mp.frozen
        noccb = int(mp.mo_occ[1].sum()) - mp.frozen
        #assert(nocca > 0 and noccb > 0)
    else:
        frozen = mp.frozen
        if len(frozen) > 0 and isinstance(frozen[0], (int, numpy.integer)):
# The same frozen orbital indices for alpha and beta orbitals
            frozen = [frozen, frozen]
        occidxa = mp.mo_occ[0] > 0
        occidxa[list(frozen[0])] = False
        occidxb = mp.mo_occ[1] > 0
        occidxb[list(frozen[1])] = False
        nocca = numpy.count_nonzero(occidxa)
        noccb = numpy.count_nonzero(occidxb)
    return nocca, noccb

def get_nmo(mp):
    if mp._nmo is not None:
        return mp._nmo
    elif isinstance(mp.frozen, (int, numpy.integer)):
        nmoa = mp.mo_occ[0].size - mp.frozen
        nmob = mp.mo_occ[1].size - mp.frozen
    elif isinstance(mp.frozen[0], (int, numpy.integer)):
        nmoa = mp.mo_occ[0].size - len(mp.frozen)
        nmob = mp.mo_occ[1].size - len(mp.frozen)
    else:
        nmoa = len(mp.mo_occ[0]) - len(mp.frozen[0])
        nmob = len(mp.mo_occ[1]) - len(mp.frozen[1])
    return nmoa, nmob


def get_frozen_mask(mp):
    '''Get boolean mask for the unrestricted reference orbitals.
    
    In the returned boolean (mask) array of frozen orbital indices, the
    element is False if it corresonds to the frozen orbital.
    '''
    moidxa = numpy.ones(mp.mo_occ[0].size, dtype=bool)
    moidxb = numpy.ones(mp.mo_occ[1].size, dtype=bool)
    if isinstance(mp.frozen, (int, numpy.integer)):
        moidxa[:mp.frozen] = False
        moidxb[:mp.frozen] = False
    elif isinstance(mp.frozen[0], (int, numpy.integer)):
        moidxa[list(mp.frozen)] = False
        moidxb[list(mp.frozen)] = False
    else:
        moidxa[list(mp.frozen[0])] = False
        moidxb[list(mp.frozen[1])] = False
    return moidxa,moidxb

def make_rdm1(mp, t2=None):
    if t2 is None: t2 = mp.t2
    from pyscf.cc import uccsd_rdm
    doo, dvv = _gamma1_intermediates(mp, t2)
    nocca, noccb, nvira, nvirb = t2[1].shape
    dov = numpy.zeros((nocca,nvira))
    dOV = numpy.zeros((noccb,nvirb))
    d1 = (doo, (dov, dOV), (dov.T, dOV.T), dvv)
    return uccsd_rdm._make_rdm1(mp, d1, with_frozen=True)

def _gamma1_intermediates(mp, t2):
    t2aa, t2ab, t2bb = t2
    dooa  = lib.einsum('imef,jmef->ij', t2aa.conj(), t2aa) *-.5
    dooa -= lib.einsum('imef,jmef->ij', t2ab.conj(), t2ab)
    doob  = lib.einsum('imef,jmef->ij', t2bb.conj(), t2bb) *-.5
    doob -= lib.einsum('mief,mjef->ij', t2ab.conj(), t2ab)

    dvva  = lib.einsum('mnae,mnbe->ab', t2aa, t2aa.conj()) * .5
    dvva += lib.einsum('mnae,mnbe->ab', t2ab, t2ab.conj())
    dvvb  = lib.einsum('mnae,mnbe->ab', t2bb, t2bb.conj()) * .5
    dvvb += lib.einsum('mnea,mneb->ab', t2ab, t2ab.conj())
    return ((dooa, doob), (dvva, dvvb))


# spin-orbital rdm2 in Chemist's notation
def make_rdm2(mp, t2=None):
    if t2 is None: t2 = mp.t2
    nmoa, nmob = nmoa0, nmob0 = mp.nmo
    nocca, noccb = nocca0, noccb0 = mp.nocc
    t2aa, t2ab, t2bb = t2

    if not (mp.frozen is 0 or mp.frozen is None):
        nmoa0 = mp.mo_occ[0].size
        nmob0 = mp.mo_occ[1].size
        nocca0 = numpy.count_nonzero(mp.mo_occ[0] > 0)
        noccb0 = numpy.count_nonzero(mp.mo_occ[1] > 0)
        moidxa, moidxb = mp.get_frozen_mask()
        oidxa = numpy.where(moidxa & (mp.mo_occ[0] > 0))[0]
        vidxa = numpy.where(moidxa & (mp.mo_occ[0] ==0))[0]
        oidxb = numpy.where(moidxb & (mp.mo_occ[1] > 0))[0]
        vidxb = numpy.where(moidxb & (mp.mo_occ[1] ==0))[0]

        dm2aa = numpy.zeros((nmoa0,nmoa0,nmoa0,nmoa0))
        dm2ab = numpy.zeros((nmoa0,nmoa0,nmob0,nmob0))
        dm2bb = numpy.zeros((nmob0,nmob0,nmob0,nmob0))

        dm2aa[oidxa[:,None,None,None],vidxa[:,None,None],oidxa[:,None],vidxa] = \
                (t2aa.transpose(0,2,1,3) - t2aa.transpose(0,3,1,2)) * .5
        dm2aa[nocca0:,:nocca0,nocca0:,:nocca0] = \
                dm2aa[:nocca0,nocca0:,:nocca0,nocca0:].transpose(1,0,3,2).conj()

        dm2bb[oidxb[:,None,None,None],vidxb[:,None,None],oidxb[:,None],vidxb] = \
                (t2bb.transpose(0,2,1,3) - t2bb.transpose(0,3,1,2)) * .5
        dm2bb[noccb0:,:noccb0,noccb0:,:noccb0] = \
                dm2bb[:noccb0,noccb0:,:noccb0,noccb0:].transpose(1,0,3,2).conj()

        dm2ab[oidxa[:,None,None,None],vidxa[:,None,None],oidxb[:,None],vidxb] = \
                t2ab.transpose(0,2,1,3)
        dm2ab[nocca0:,:nocca0,noccb0:,:noccb0] = \
                dm2ab[:nocca0,nocca0:,:noccb0,noccb0:].transpose(1,0,3,2).conj()
    else:

        dm2aa = numpy.zeros((nmoa0,nmoa0,nmoa0,nmoa0))
        dm2ab = numpy.zeros((nmoa0,nmoa0,nmob0,nmob0))
        dm2bb = numpy.zeros((nmob0,nmob0,nmob0,nmob0))

        dm2aa[:nocca0,nocca0:,:nocca0,nocca0:] = \
                (t2aa.transpose(0,2,1,3) - t2aa.transpose(0,3,1,2)) * .5
        dm2aa[nocca0:,:nocca0,nocca0:,:nocca0] = \
                dm2aa[:nocca0,nocca0:,:nocca0,nocca0:].transpose(1,0,3,2).conj()

        dm2bb[:noccb0,noccb0:,:noccb0,noccb0:] = \
                (t2bb.transpose(0,2,1,3) - t2bb.transpose(0,3,1,2)) * .5
        dm2bb[noccb0:,:noccb0,noccb0:,:noccb0] = \
                dm2bb[:noccb0,noccb0:,:noccb0,noccb0:].transpose(1,0,3,2).conj()

        dm2ab[:nocca0,nocca0:,:noccb0,noccb0:] = t2ab.transpose(0,2,1,3)
        dm2ab[nocca0:,:nocca0,noccb0:,:noccb0] = t2ab.transpose(2,0,3,1).conj()

    dm1a, dm1b = make_rdm1(mp, t2)
    dm1a[numpy.diag_indices(nocca0)] -= 1
    dm1b[numpy.diag_indices(noccb0)] -= 1

    for i in range(nocca0):
        dm2aa[i,i,:,:] += dm1a
        dm2aa[:,:,i,i] += dm1a
        dm2aa[:,i,i,:] -= dm1a
        dm2aa[i,:,:,i] -= dm1a
        dm2ab[i,i,:,:] += dm1b
    for i in range(noccb0):
        dm2bb[i,i,:,:] += dm1b
        dm2bb[:,:,i,i] += dm1b
        dm2bb[:,i,i,:] -= dm1b
        dm2bb[i,:,:,i] -= dm1b
        dm2ab[:,:,i,i] += dm1a

    for i in range(nocca0):
        for j in range(nocca0):
            dm2aa[i,i,j,j] += 1
            dm2aa[i,j,j,i] -= 1
    for i in range(noccb0):
        for j in range(noccb0):
            dm2bb[i,i,j,j] += 1
            dm2bb[i,j,j,i] -= 1
    for i in range(nocca0):
        for j in range(noccb0):
            dm2ab[i,i,j,j] += 1

    return dm2aa, dm2ab, dm2bb


class UMP2(mp2.MP2):

    get_nocc = get_nocc
    get_nmo = get_nmo
    get_frozen_mask = get_frozen_mask

    @lib.with_doc(mp2.MP2.kernel.__doc__)
    def kernel(self, mo_energy=None, mo_coeff=None, eris=None, with_t2=True):
        return mp2.MP2.kernel(self, mo_energy, mo_coeff, eris, with_t2, kernel)

    def ao2mo(self, mo_coeff=None):
        if mo_coeff is None: mo_coeff = self.mo_coeff
        return _make_eris(self, mo_coeff, verbose=self.verbose)

    make_rdm1 = make_rdm1
    make_rdm2 = make_rdm2

    def nuc_grad_method(self):
        from pyscf.mp import ump2_grad
        return ump2_grad.Gradients(self)


class _ChemistsERIs(mp2._ChemistsERIs):
    def __init__(self, mp, mo_coeff=None):
        if mo_coeff is None:
            mo_coeff = mp.mo_coeff
        moidx = mp.get_frozen_mask()
        self.mo_coeff = mo_coeff = \
                (mo_coeff[0][:,moidx[0]], mo_coeff[1][:,moidx[1]])

def _make_eris(mp, mo_coeff=None, ao2mofn=None, verbose=None):
    log = logger.new_logger(mp, verbose)
    time0 = (time.clock(), time.time())
    eris = _ChemistsERIs(mp, mo_coeff)

    nocca, noccb = mp.get_nocc()
    nmoa, nmob = mp.get_nmo()
    nao = eris.mo_coeff[0].shape[0]
    nmo_pair = nmoa * (nmoa+1) // 2
    nao_pair = nao * (nao+1) // 2
    mem_incore = (nao_pair**2 + nmo_pair**2) * 8/1e6
    mem_now = lib.current_memory()[0]
    max_memory = max(2000, mp.max_memory*.9-mem_now)

    moa = eris.mo_coeff[0]
    mob = eris.mo_coeff[1]
    orboa = moa[:,:nocca]
    orbob = mob[:,:noccb]
    orbva = moa[:,nocca:]
    orbvb = mob[:,noccb:]

    if (mp.mol.incore_anyway or
        (mp._scf._eri is not None and mem_incore+mem_now < mp.max_memory)):
        log.debug('transform (ia|jb) incore')
        if callable(ao2mofn):
            eris.ovov = ao2mofn((orboa,orbva,orboa,orbva)).reshape(nocc*nvir,nocc*nvir)
            eris.ovOV = ao2mofn((orboa,orbva,orbob,orbvb)).reshape(nocc*nvir,nocc*nvir)
            eris.OVOV = ao2mofn((orbob,orbvb,orbob,orbvb)).reshape(nocc*nvir,nocc*nvir)
        else:
            eris.ovov = ao2mo.general(mp._scf._eri, (orboa,orbva,orboa,orbva))
            eris.ovOV = ao2mo.general(mp._scf._eri, (orboa,orbva,orbob,orbvb))
            eris.OVOV = ao2mo.general(mp._scf._eri, (orbob,orbvb,orbob,orbvb))

    elif hasattr(mp._scf, 'with_df'):
        logger.warn(mp, 'UMP2 detected DF being used in the HF object. '
                    'MO integrals are computed based on the DF 3-index tensors.\n'
                    'It\'s recommended to use DF-UMP2 module.')
        log.debug('transform (ia|jb) with_df')
        eris.ovov = mp._scf.with_df.ao2mo((orboa,orbva,orboa,orbva))
        eris.ovOV = mp._scf.with_df.ao2mo((orboa,orbva,orbob,orbvb))
        eris.OVOV = mp._scf.with_df.ao2mo((orbob,orbvb,orbob,orbvb))

    else:
        log.debug('transform (ia|jb) outcore')
        eris.feri = lib.H5TmpFile()
        _ao2mo_ovov(mp, (orboa,orbva,orbob,orbvb), eris.feri, max_memory, log)
        eris.ovov = eris.feri['ovov']
        eris.ovOV = eris.feri['ovOV']
        eris.OVOV = eris.feri['OVOV']

    time1 = log.timer('Integral transformation', *time0)
    return eris

def _ao2mo_ovov(mp, orbs, feri, max_memory=2000, verbose=None):
    time0 = (time.clock(), time.time())
    log = logger.new_logger(mp, verbose)
    orboa = numpy.asarray(orbs[0], order='F')
    orbva = numpy.asarray(orbs[1], order='F')
    orbob = numpy.asarray(orbs[2], order='F')
    orbvb = numpy.asarray(orbs[3], order='F')
    nao, nocca = orboa.shape
    noccb = orbob.shape[1]
    nvira = orbva.shape[1]
    nvirb = orbvb.shape[1]

    mol = mp.mol
    int2e = mol._add_suffix('int2e')
    ao2mopt = _ao2mo.AO2MOpt(mol, int2e, 'CVHFnr_schwarz_cond',
                             'CVHFsetnr_direct_scf')
    nbas = mol.nbas
    assert(nvira <= nao)
    assert(nvirb <= nao)

    ao_loc = mol.ao_loc_nr()
    dmax = max(4, min(nao/3, numpy.sqrt(max_memory*.95e6/8/(nao+nocca)**2)))
    sh_ranges = ao2mo.outcore.balance_partition(ao_loc, dmax)
    dmax = max(x[2] for x in sh_ranges)
    eribuf = numpy.empty((nao,dmax,dmax,nao))
    ftmp = lib.H5TmpFile()
    disk = (nocca**2*(nao*(nao+dmax)/2+nvira**2) +
            noccb**2*(nao*(nao+dmax)/2+nvirb**2) +
            nocca*noccb*(nao**2+nvira*nvirb))
    log.debug('max_memory %s MB (dmax = %s) required disk space %g MB',
              max_memory, dmax, disk*8/1e6)

    fint = gto.moleintor.getints4c
    aa_blk_slices = []
    ab_blk_slices = []
    count_ab = 0
    count_aa = 0
    time1 = time0
    with lib.call_in_background(ftmp.__setitem__) as save:
        for ish0, ish1, ni in sh_ranges:
            for jsh0, jsh1, nj in sh_ranges:
                i0, i1 = ao_loc[ish0], ao_loc[ish1]
                j0, j1 = ao_loc[jsh0], ao_loc[jsh1]

                eri = fint(int2e, mol._atm, mol._bas, mol._env,
                           shls_slice=(0,nbas,ish0,ish1, jsh0,jsh1,0,nbas),
                           aosym='s1', ao_loc=ao_loc, cintopt=ao2mopt._cintopt,
                           out=eribuf)
                tmp_i = lib.ddot(orboa.T, eri.reshape(nao,(i1-i0)*(j1-j0)*nao))
                tmp_li = lib.ddot(orbob.T, tmp_i.reshape(nocca*(i1-i0)*(j1-j0),nao).T)
                tmp_li = tmp_li.reshape(noccb,nocca,(i1-i0),(j1-j0))
                save('ab/%d'%count_ab, tmp_li.transpose(1,0,2,3))
                ab_blk_slices.append((i0,i1,j0,j1))
                count_ab += 1

                if ish0 >= jsh0:
                    tmp_li = lib.ddot(orboa.T, tmp_i.reshape(nocca*(i1-i0)*(j1-j0),nao).T)
                    tmp_li = tmp_li.reshape(nocca,nocca,(i1-i0),(j1-j0))
                    save('aa/%d'%count_aa, tmp_li.transpose(1,0,2,3))

                    tmp_i = lib.ddot(orbob.T, eri.reshape(nao,(i1-i0)*(j1-j0)*nao))
                    tmp_li = lib.ddot(orbob.T, tmp_i.reshape(noccb*(i1-i0)*(j1-j0),nao).T)
                    tmp_li = tmp_li.reshape(noccb,noccb,(i1-i0),(j1-j0))
                    save('bb/%d'%count_aa, tmp_li.transpose(1,0,2,3))
                    aa_blk_slices.append((i0,i1,j0,j1))
                    count_aa += 1

                time1 = log.timer_debug1('partial ao2mo [%d:%d,%d:%d]' %
                                         (ish0,ish1,jsh0,jsh1), *time1)
    time1 = time0 = log.timer('mp2 ao2mo_ovov pass1', *time0)
    eri = eribuf = tmp_i = tmp_li = None

    fovov = feri.create_dataset('ovov', (nocca*nvira,nocca*nvira), 'f8',
                                chunks=(nvira,nvira))
    fovOV = feri.create_dataset('ovOV', (nocca*nvira,noccb*nvirb), 'f8',
                                chunks=(nvira,nvirb))
    fOVOV = feri.create_dataset('OVOV', (noccb*nvirb,noccb*nvirb), 'f8',
                                chunks=(nvirb,nvirb))
    occblk = int(min(max(nocca,noccb),
                     max(4, 250/nocca, max_memory*.9e6/8/(nao**2*nocca)/5)))

    def load_aa(h5g, nocc, i0, eri):
        if i0 < nocc:
            i1 = min(i0+occblk, nocc)
            for k, (p0,p1,q0,q1) in enumerate(aa_blk_slices):
                eri[:i1-i0,:,p0:p1,q0:q1] = h5g[str(k)][i0:i1]
                if p0 != q0:
                    dat = numpy.asarray(h5g[str(k)][:,i0:i1])
                    eri[:i1-i0,:,q0:q1,p0:p1] = dat.transpose(1,0,3,2)

    def load_ab(h5g, nocca, i0, eri):
        if i0 < nocca:
            i1 = min(i0+occblk, nocca)
            for k, (p0,p1,q0,q1) in enumerate(ab_blk_slices):
                eri[:i1-i0,:,p0:p1,q0:q1] = h5g[str(k)][i0:i1]

    def save(h5dat, nvir, i0, i1, dat):
        for i in range(i0, i1):
            h5dat[i*nvir:(i+1)*nvir] = dat[i-i0].reshape(nvir,-1)

    with lib.call_in_background(save) as bsave:
        with lib.call_in_background(load_aa) as prefetch:
            buf_prefecth = numpy.empty((occblk,nocca,nao,nao))
            buf = numpy.empty_like(buf_prefecth)
            load_aa(ftmp['aa'], nocca, 0, buf_prefecth)
            for i0, i1 in lib.prange(0, nocca, occblk):
                buf, buf_prefecth = buf_prefecth, buf
                prefetch(ftmp['aa'], nocca, i1, buf_prefecth)
                eri = buf[:i1-i0].reshape((i1-i0)*nocca,nao,nao)
                dat = _ao2mo.nr_e2(eri, orbva, (0,nvira,0,nvira), 's1', 's1')
                bsave(fovov, nvira, i0, i1,
                      dat.reshape(i1-i0,nocca,nvira,nvira).transpose(0,2,1,3))
                time1 = log.timer_debug1('pass2 ao2mo for aa [%d:%d]' % (i0,i1), *time1)

            buf_prefecth = numpy.empty((occblk,noccb,nao,nao))
            buf = numpy.empty_like(buf_prefecth)
            load_aa(ftmp['bb'], noccb, 0, buf_prefecth)
            for i0, i1 in lib.prange(0, noccb, occblk):
                buf, buf_prefecth = buf_prefecth, buf
                prefetch(ftmp['bb'], noccb, i1, buf_prefecth)
                eri = buf[:i1-i0].reshape((i1-i0)*noccb,nao,nao)
                dat = _ao2mo.nr_e2(eri, orbvb, (0,nvirb,0,nvirb), 's1', 's1')
                bsave(fOVOV, nvirb, i0, i1,
                      dat.reshape(i1-i0,noccb,nvirb,nvirb).transpose(0,2,1,3))
                time1 = log.timer_debug1('pass2 ao2mo for bb [%d:%d]' % (i0,i1), *time1)

        orbvab = numpy.asarray(numpy.hstack((orbva, orbvb)), order='F')
        with lib.call_in_background(load_ab) as prefetch:
            load_ab(ftmp['ab'], nocca, 0, buf_prefecth)
            for i0, i1 in lib.prange(0, nocca, occblk):
                buf, buf_prefecth = buf_prefecth, buf
                prefetch(ftmp['ab'], nocca, i1, buf_prefecth)
                eri = buf[:i1-i0].reshape((i1-i0)*noccb,nao,nao)
                dat = _ao2mo.nr_e2(eri, orbvab, (0,nvira,nvira,nvira+nvirb), 's1', 's1')
                bsave(fovOV, nvira, i0, i1,
                      dat.reshape(i1-i0,noccb,nvira,nvirb).transpose(0,2,1,3))
                time1 = log.timer_debug1('pass2 ao2mo for ab [%d:%d]' % (i0,i1), *time1)

    time0 = log.timer('mp2 ao2mo_ovov pass2', *time0)


if __name__ == '__main__':
    from pyscf import scf
    from pyscf import gto
    mol = gto.Mole()
    mol.atom = [['O', (0.,   0., 0.)],
                ['O', (1.21, 0., 0.)]]
    mol.basis = 'cc-pvdz'
    mol.spin = 2
    mol.build()
    mf = scf.UHF(mol).run()
    frozen = [[0,1],[0,1]]
    pt = UMP2(mf, frozen=frozen)
    emp2, t2 = pt.kernel()
    print(emp2 - -0.345306881488508)

    pt.max_memory = 1
    emp2, t2 = pt.kernel()
    print(emp2 - -0.345306881488508)

    dm1a,dm1b = pt.make_rdm1()
    dm2aa,dm2ab,dm2bb = pt.make_rdm2()
    mo_a = mf.mo_coeff[0]
    mo_b = mf.mo_coeff[1]
    nmoa = mo_a.shape[1]
    nmob = mo_b.shape[1]
    eriaa = ao2mo.kernel(mf._eri, mo_a, compact=False).reshape([nmoa]*4)
    eribb = ao2mo.kernel(mf._eri, mo_b, compact=False).reshape([nmob]*4)
    eriab = ao2mo.kernel(mf._eri, (mo_a,mo_a,mo_b,mo_b), compact=False)
    eriab = eriab.reshape([nmoa,nmoa,nmob,nmob])
    hcore = mf.get_hcore()
    h1a = reduce(numpy.dot, (mo_a.T.conj(), hcore, mo_a))
    h1b = reduce(numpy.dot, (mo_b.T.conj(), hcore, mo_b))
    e1 = numpy.einsum('ij,ji', h1a, dm1a)
    e1+= numpy.einsum('ij,ji', h1b, dm1b)
    e1+= numpy.einsum('ijkl,jilk', eriaa, dm2aa) * .5
    e1+= numpy.einsum('ijkl,jilk', eriab, dm2ab)
    e1+= numpy.einsum('ijkl,jilk', eribb, dm2bb) * .5
    e1+= mol.energy_nuc()
    print(e1 - pt.e_tot)

    pt = UMP2(scf.density_fit(mf, 'weigend'))
    print(pt.kernel()[0] - -0.3503781525098727)