/* Persistent QRTR transport on Renoir PCIe MHI. Included after boot helpers.
 * A single worker owns all MHI pointers; QMI callers only enqueue copies. */
static LCK_MTX_DECLARE(renoir_link_lock,&wifi_lock_group);
static struct {
	volatile bool wanted,running,failed;
	vm_offset_t bar;
	struct glink_packet *first,*last;
	unsigned queued;
} renoir_link;

static int
renoir_link_send(const void *data,uint32_t length)
{
	if (!data || !length || length>8192) { return EMSGSIZE; }
	struct glink_packet *p=kalloc_data(sizeof(*p)+length,Z_WAITOK);
	if (!p) { return ENOMEM; }
	p->next=NULL;p->length=length;memcpy(p->data,data,length);
	lck_mtx_lock(&renoir_link_lock);
	if (!renoir_link.wanted || renoir_link.queued>=64) {
		lck_mtx_unlock(&renoir_link_lock);kfree_data(p,sizeof(*p)+length);return ENETDOWN;
	}
	if (renoir_link.last) { renoir_link.last->next=p; } else { renoir_link.first=p; }
	renoir_link.last=p;renoir_link.queued++;
	lck_mtx_unlock(&renoir_link_lock);return 0;
}

static void
renoir_link_input(const uint8_t *data,uint32_t length)
{
	/* CNSS2 uses optional BDF response flags to select internal PA power. */
	if (length>=39 && data[32]==2 && data[35]==0x25 && !data[36]) {
		unsigned bytes=data[37]|data[38]<<8;
		if (bytes<=length-39) {
			for (unsigned i=39;i<39+bytes;) {
				if (39+bytes-i<3) { break; }
				unsigned tag=data[i],size=data[i+1]|data[i+2]<<8;i+=3;
				if (size>39+bytes-i) { break; }
				if (tag==0x10 && size==8) {
					uint64_t flags;memcpy(&flags,data+i,8);
					say("renoir-wifi: BDF host flags %#llx (external PA %u)\n",flags,(unsigned)(flags&1));
					vm_offset_t tcs=ml_io_map(0xb2e5000,0x1000);
					if (tcs) { say("renoir-wifi: RF PA TCS address %#x data %#x (read only)\n",rd(tcs+0x9c0),rd(tcs+0x9c4)); }
				}
				i+=size;
			}
		}
	}
	lck_mtx_lock(&qrtr_calling);qrtr_input(data,length);lck_mtx_unlock(&qrtr_calling);
}

static void
renoir_link_flush(void)
{
	if (!renoir_link.wanted || !renoir_bhi.tx_done) { return; }
	lck_mtx_lock(&renoir_link_lock);
	struct glink_packet *p=renoir_link.first;
	if (p) {
		renoir_link.first=p->next;if (!renoir_link.first) { renoir_link.last=NULL; }
		renoir_link.queued--;
	}
	lck_mtx_unlock(&renoir_link_lock);
	if (!p) { return; }
	vm_offset_t buffer=renoir_bhi.control_alias+0xe000;
	for (unsigned offset=0;offset<p->length;offset+=4) {
		uint32_t value=0;unsigned n=p->length-offset>4 ? 4 : p->length-offset;
		memcpy(&value,p->data+offset,n);wr(buffer+offset,value);
	}
	renoir_mhi_submit_tx(renoir_link.bar,p->length);
	kfree_data(p,sizeof(*p)+p->length);
}

/* CNSS2's 0x420000-byte RDDM image, in an independently mapped boot arena.
 * RX vectors are published before mission mode; no firmware pool is reused. */
static bool
renoir_rddm_prepare(vm_offset_t bar)
{
	uint32_t start=renoir_bhi.control+0x10000, offset=rd(bar+0x2c);
	if (start>renoir_bhi.allocation || 0x420000>renoir_bhi.allocation-start ||
	    !offset || (offset&3) || offset>0x10000-0x80) { return false; }
	vm_offset_t vectors=renoir_bhi.control_alias+0x8100;
	for (unsigned i=0;i<9;i++) {
		renoir_mhi_write64(vectors+i*16,RADIO_ADDRESSES+start+i*0x80000);
		renoir_mhi_write64(vectors+i*16+8,i==8 ? 0x20000 : 0x80000);
	}
	__asm__ volatile("dsb sy" ::: "memory");
	renoir_mhi_write64(bar+offset+0x60,RADIO_ADDRESSES+renoir_bhi.control+0x8100);
	wr(bar+offset+0x68,9*16);
	__asm__ volatile("dsb sy" ::: "memory");
	wr(bar+offset+0x70,1);
	return true;
}

static void
renoir_rddm_report(vm_offset_t bar)
{
	uint32_t bhie=renoir_bhi.bhie_offset, status=0;
	if (!bhie || (bhie&3) || bhie>0x10000-0x80) { return; }
	for (unsigned ms=0;ms<10000;ms++) {
		status=rd(bar+bhie+0x78);if (status>>30) { break; }sleep_ms(1);
	}
	say("renoir-wifi: RDDM transfer status %#x\n",status);
	if (status>>30!=2) { return; }
	uint32_t start=renoir_bhi.control+0x10000;
	vm_offset_t dump=renoir_bhi.buffer+start;
	for (vm_offset_t line=dump;line<dump+0x420000;line+=64) {
		__asm__ volatile("dc ivac, %0" : : "r"(line) : "memory");
	}
	__asm__ volatile("dsb sy" ::: "memory");
	uint32_t size;const uint8_t *sfr=renoir_rddm_sfr((void *)dump,0x420000,&size);
	if (sfr) {
		char reason[513];unsigned n=size<512 ? size : 512;
		memcpy(reason,sfr,n);reason[n]=0;
		for (unsigned i=0;i<n;i++) { if ((unsigned char)reason[i]<32 && reason[i]!='\n' && reason[i]!='\t') { reason[i]=' '; } }
		say("renoir-wifi: firmware failure reason: %s\n",reason);
	}
}

static void
renoir_link_thread(__unused void *argument,__unused wait_result_t result)
{
	link_thread_is=current_thread();
	while (renoir_link.wanted) {
		if (!renoir_mhi_poll_boot_events(renoir_link.bar) || (rd(renoir_link.bar+0x48)&4)) {
			say("renoir-wifi: runtime failed MHI %#x EE %#x BHI error %#x events %u\n",rd(renoir_link.bar+0x48),rd(renoir_link.bar+renoir_bhi.bhi_offset+0x28),rd(renoir_link.bar+renoir_bhi.bhi_offset+0x30),renoir_bhi.event_count);
			renoir_rddm_report(renoir_link.bar);
			renoir_link.failed=true;renoir_transport_ready=false;
			lck_mtx_lock(&renoir_link_lock);renoir_link.wanted=false;lck_mtx_unlock(&renoir_link_lock);break;
		}
		lck_mtx_lock(&qrtr_calling);qrtr_fresh();lck_mtx_unlock(&qrtr_calling);
		renoir_link_flush();sleep_ms(1);
	}
	link_thread_is=THREAD_NULL;renoir_link.running=false;
	thread_terminate(current_thread());
}

static bool
renoir_mhi_runtime(vm_offset_t bar)
{
	uint64_t began=now_us();
	thread_t worker;renoir_link.bar=bar;renoir_link.wanted=true;renoir_link.running=true;
	renoir_link.failed=false;renoir_bhi.tx_done=true;renoir_bhi.tx_slot=0;
	radio_space.next=0x8000000;radio_space.wanted=2;
	renoir_mhi_write64(bar+0x88,RADIO_ADDRESSES+RADIO_ADDRESSES_SIZE-1);
	renoir_mhi_write64(bar+0xa0,RADIO_ADDRESSES+RADIO_ADDRESSES_SIZE-1);
	if (!renoir_rddm_prepare(bar)) { renoir_link.wanted=false;renoir_link.running=false;return false; }
	renoir_transport_ready=true;radio_qrtr_send=renoir_link_send;renoir_qrtr_input=renoir_link_input;
	redwood_qmi_set_transport(&qrtr_ops);
	renoir_mhi_post_rx(bar);
	if (kernel_thread_start(renoir_link_thread,NULL,&worker)!=KERN_SUCCESS) {
		renoir_link.wanted=false;renoir_link.running=false;renoir_transport_ready=false;
		radio_qrtr_send=NULL;renoir_qrtr_input=NULL;return false;
	}
	thread_deallocate(worker);
	struct qrtr_control hello={.command=QRTR_HELLO};
	int error=qrtr_out_packet(QRTR_HELLO,QRTR_CONTROL,0xffffffff,QRTR_CONTROL,&hello,sizeof(hello));
	if (!error) { error=redwood_lx_start(); }
	say("renoir-wifi: ath11k PCIe start result %d transport failed %u\n",error,renoir_link.failed);
	if (!error && whole) {
		join_given(began);
		tell("renoir-wifi: station offered to iOS; PCIe/MHI kept active\n");
		while (renoir_session_wanted && renoir_link.wanted && !renoir_link.failed) { sleep_ms(50); }
	}

	redwood_lx_stop();
	lck_mtx_lock(&renoir_link_lock);renoir_link.wanted=false;lck_mtx_unlock(&renoir_link_lock);
	for (unsigned ms=0;ms<5000 && renoir_link.running;ms++) { sleep_ms(1); }
	if (renoir_link.running) { panic("renoir-wifi: MHI worker did not stop before DMA teardown"); }
	renoir_transport_ready=false;radio_qrtr_send=NULL;renoir_qrtr_input=NULL;
	while (renoir_link.first) {
		struct glink_packet *p=renoir_link.first;renoir_link.first=p->next;
		kfree_data(p,sizeof(*p)+p->length);
	}
	renoir_link.last=NULL;renoir_link.queued=0;
	return !error && !renoir_link.failed;
}
