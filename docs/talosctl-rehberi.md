# talosctl Komut Referans Rehberi

**Sürüm:** v1.12.1
**Tarih:** 2026-03-06

> `talosctl`, Talos Linux tarafından oluşturulan Kubernetes node'larının band dışı (out-of-band) yönetimi için CLI aracıdır.

---

## İçindekiler

1. [Genel Kullanım](#genel-kullanım)
2. [Ortak Bayraklar (Global Flags)](#ortak-bayraklar)
3. [Küme Yönetimi Komutları](#küme-yönetimi-komutları)
4. [Node İzleme ve Tanılama](#node-izleme-ve-tanılama)
5. [Konteyner ve Servis Yönetimi](#konteyner-ve-servis-yönetimi)
6. [Dosya Sistemi ve Disk İşlemleri](#dosya-sistemi-ve-disk-i̇şlemleri)
7. [Ağ İşlemleri](#ağ-i̇şlemleri)
8. [etcd Yönetimi](#etcd-yönetimi)
9. [Yapılandırma Yönetimi (config)](#yapılandırma-yönetimi-config)
10. [Sertifika ve Anahtar Üretimi (gen)](#sertifika-ve-anahtar-üretimi-gen)
11. [Makine Yapılandırması (machineconfig)](#makine-yapılandırması-machineconfig)
12. [Image Yönetimi](#image-yönetimi)
13. [Yerel Küme Yönetimi (cluster)](#yerel-küme-yönetimi-cluster)
14. [Diğer Komutlar](#diğer-komutlar)

---

## Genel Kullanım

```bash
talosctl [komut] [bayraklar]
```

---

## Ortak Bayraklar

Çoğu komutta geçerli olan ortak bayraklar:

| Bayrak | Kısa | Açıklama |
|--------|------|----------|
| `--talosconfig` | | Talos yapılandırma dosyasının yolu (`~/.talos/config`) |
| `--context` | | Kullanılacak context adı |
| `--endpoints` | `-e` | Varsayılan endpoint'leri geçersiz kıl |
| `--nodes` | `-n` | Hedef node'ları belirt |
| `--cluster` | `-c` | Proxy endpoint kullanıyorsa bağlanılacak küme |
| `--help` | `-h` | Yardım mesajı |

---

## Küme Yönetimi Komutları

### `apply-config` (takma ad: `apply`)
Node'a yeni bir yapılandırma uygula.

```bash
talosctl apply-config --file config.yaml
talosctl apply-config -f config.yaml -n 192.168.1.10
talosctl apply-config -f config.yaml --mode staged          # Bir sonraki yeniden başlatmada uygula
talosctl apply-config -f config.yaml --mode try             # Geçici uygula (timeout sonra geri al)
talosctl apply-config -f config.yaml --dry-run              # Değişiklikleri önizle
talosctl apply-config -f config.yaml --insecure             # Bakım modunda uygula (auth yok)
```

**Modlar:**
- `auto` — Otomatik seç (varsayılan)
- `no-reboot` — Yeniden başlatma olmadan uygula
- `reboot` — Yeniden başlatarak uygula
- `staged` — Bir sonraki yeniden başlatmada uygula
- `try` — Geçici uygula (1 dakika sonra geri alınır, `--timeout` ile değiştirilebilir)

**Bayraklar:**
- `-f, --file` — Yapılandırma dosyası yolu
- `-p, --config-patch` — Göndermeden önce uygulanacak patch listesi
- `-m, --mode` — Uygulama modu
- `--dry-run` — Kuru çalıştırma
- `-i, --insecure` — Şifresiz bakım servisi ile uygula
- `--cert-fingerprint` — Kabul edilecek sunucu sertifika parmak izleri
- `--timeout` — Try modunda geri alma süresi (varsayılan: 1 dakika)

---

### `bootstrap`
Belirtilen node üzerinde etcd kümesini başlat.

```bash
talosctl bootstrap -n 192.168.1.10
```

> **Not:** Talos kümesi oluşturulduğunda, control plane node'larındaki etcd servisi join döngüsüne girer. `bootstrap` komutu ile ilk node etcd'yi başlatır, diğerleri bu node'a katılır.

---

### `health`
Küme sağlığını kontrol et.

```bash
talosctl health
talosctl health --wait-timeout 10m
talosctl health --control-plane-nodes 192.168.1.10,192.168.1.11
talosctl health --worker-nodes 192.168.1.20
```

---

### `upgrade`
Hedef node üzerinde Talos'u yükselt.

```bash
talosctl upgrade --image ghcr.io/siderolabs/installer:v1.12.0 -n 192.168.1.10
talosctl upgrade --image ghcr.io/siderolabs/installer:v1.12.0 --preserve
talosctl upgrade --image ghcr.io/siderolabs/installer:v1.12.0 --stage
```

**Bayraklar:**
- `--image` — Kullanılacak installer image'ı
- `--preserve` — Node verilerini koru
- `--stage` — Bir sonraki yeniden başlatmada yükselt
- `--force` — Sürüm kontrolünü atla

---

### `upgrade-k8s`
Talos kümesinde Kubernetes control plane'i yükselt.

```bash
talosctl upgrade-k8s --to 1.32.0
talosctl upgrade-k8s --to 1.32.0 --dry-run
```

---

### `reboot`
Node'u yeniden başlat.

```bash
talosctl reboot -n 192.168.1.10
talosctl reboot --mode hard -n 192.168.1.10   # Güçlü yeniden başlatma
talosctl reboot --wait                          # Tamamlanana kadar bekle
```

---

### `shutdown`
Node'u kapat.

```bash
talosctl shutdown -n 192.168.1.10
talosctl shutdown --force -n 192.168.1.10
```

---

### `reset`
Node'u sıfırla.

```bash
talosctl reset -n 192.168.1.10
talosctl reset --graceful=false --reboot -n 192.168.1.10
talosctl reset --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL
```

> **Uyarı:** Bu komut node'u fabrika ayarlarına döndürür!

---

### `rollback`
Node'u önceki kuruluma geri al.

```bash
talosctl rollback -n 192.168.1.10
```

---

### `rotate-ca`
Küme CA'larını (Talos ve Kubernetes API) döndür.

```bash
talosctl rotate-ca
talosctl rotate-ca --dry-run
```

---

### `kubeconfig`
Node'dan admin kubeconfig'i indir.

```bash
talosctl kubeconfig                    # ~/.kube/config'e yaz
talosctl kubeconfig ./my-kubeconfig    # Belirtilen yola yaz
talosctl kubeconfig --merge=false      # Merge etme, üzerine yaz
talosctl kubeconfig --force            # Mevcut dosyanın üzerine yaz
```

---

### `support`
Küme hakkında debug bilgisi topla.

```bash
talosctl support
talosctl support --output talos-support.zip
talosctl support -n 192.168.1.10,192.168.1.11
```

---

## Node İzleme ve Tanılama

### `dashboard`
Node genel bakışı, loglar ve gerçek zamanlı metriklerle küme dashboard'u.

```bash
talosctl dashboard
talosctl dashboard -n 192.168.1.10
```

---

### `dmesg`
Kernel loglarını getir.

```bash
talosctl dmesg
talosctl dmesg --follow    # Canlı takip
talosctl dmesg --tail 100  # Son 100 satır
```

---

### `events`
Runtime olaylarını akış olarak al.

```bash
talosctl events
talosctl events --watch
talosctl events --tail 50
talosctl events --with-actor
```

---

### `get`
Belirli bir kaynağı veya kaynak listesini getir.

```bash
talosctl get rd                      # Tüm kullanılabilir kaynak türlerini listele
talosctl get nodestatus
talosctl get networkinterface
talosctl get service
talosctl get service -o json         # JSON çıktı
talosctl get service -o yaml         # YAML çıktı
talosctl get service --watch         # Değişiklikleri izle
talosctl get service kubelet -o yaml # Belirli bir kaynağı getir
```

---

### `memory`
Bellek kullanımını göster.

```bash
talosctl memory
talosctl memory --verbose
```

---

### `mounts`
Mount noktalarını listele.

```bash
talosctl mounts
```

---

### `processes`
Çalışan süreçleri listele.

```bash
talosctl processes
talosctl processes --sort-by cpu     # CPU'ya göre sırala
talosctl processes --sort-by rss     # Belleğe göre sırala
talosctl processes --watch           # Canlı izle (htop gibi)
```

---

### `cgroups`
Cgroup kullanım bilgisini getir.

```bash
talosctl cgroups
talosctl cgroups --preset=cpuacct
```

---

### `time`
Geçerli sunucu zamanını getir.

```bash
talosctl time
talosctl time --check pool.ntp.org   # NTP sunucusuyla karşılaştır
```

---

### `version`
Sürümü yazdır.

```bash
talosctl version
talosctl version --short
talosctl version --client            # Sadece client sürümü
```

---

### `inspect dependencies`
Controller-resource bağımlılıklarını graphviz grafiği olarak göster.

```bash
talosctl inspect dependencies
talosctl inspect dependencies | dot -Tsvg > deps.svg
```

---

## Konteyner ve Servis Yönetimi

### `containers`
Konteynerleri listele.

```bash
talosctl containers
talosctl containers -k                          # Kubernetes namespace'i
talosctl containers --namespace system          # Sistem namespace'i
```

---

### `logs`
Servis loglarını getir.

```bash
talosctl logs kubelet
talosctl logs kubelet --follow           # Canlı takip
talosctl logs kubelet --tail-lines 100   # Son 100 satır
talosctl logs -k kube-system/coredns-xxx # Kubernetes pod logu
```

---

### `service`
Servis durumunu getir veya kontrol et.

```bash
talosctl service                     # Tüm servisleri listele
talosctl service kubelet             # Kubelet durumunu göster
talosctl service kubelet start       # Servisi başlat
talosctl service kubelet stop        # Servisi durdur
talosctl service kubelet restart     # Servisi yeniden başlat
```

---

### `restart`
Bir süreci yeniden başlat.

```bash
talosctl restart -k kube-system/coredns-xxx/coredns  # Kubernetes konteyner
```

---

### `stats`
Konteyner istatistiklerini getir.

```bash
talosctl stats
talosctl stats -k    # Kubernetes konteynerleri
```

---

## Dosya Sistemi ve Disk İşlemleri

### `list`
Dizin listesini getir.

```bash
talosctl list /
talosctl list /etc
talosctl list --long /etc       # Detaylı liste
talosctl list --recurse /etc    # Alt dizinlerle birlikte
talosctl list -r --depth 2 /etc # 2 seviye derinliğe kadar
talosctl list --humanize /var   # İnsan okunabilir boyutlar
```

---

### `read`
Makinedeki bir dosyayı oku.

```bash
talosctl read /etc/os-release
talosctl read /proc/cpuinfo
```

---

### `copy`
Node'dan veri kopyala.

```bash
talosctl copy /etc/talos/config ./talos-config.yaml
talosctl copy /var/log/talos/talos.log ./talos.log
```

---

### `usage`
Disk kullanımını getir.

```bash
talosctl usage /
talosctl usage /var --threshold 100MB
talosctl usage --all /
```

---

### `wipe`
Blok cihazı veya volume'ü sil.

```bash
talosctl wipe disk --disk sda
talosctl wipe system-disk
```

> **Uyarı:** Geri alınamaz işlem!

---

### `meta`
META bölümündeki anahtarları yaz ve sil.

```bash
talosctl meta write 0x22 "değer"   # Anahtar yaz
talosctl meta delete 0x22           # Anahtar sil
```

---

## Ağ İşlemleri

### `netstat`
Ağ bağlantılarını ve soketleri göster.

```bash
talosctl netstat
talosctl netstat --all               # Tüm soketler
talosctl netstat --listening         # Sadece dinleyenler
talosctl netstat --tcp               # Sadece TCP
talosctl netstat --udp               # Sadece UDP
talosctl netstat --program           # Süreç bilgisi göster
talosctl netstat --extend            # Genişletilmiş bilgi
```

---

### `pcap`
Node'dan ağ paketlerini yakala.

```bash
talosctl pcap --interface eth0
talosctl pcap --interface eth0 --output capture.pcap
talosctl pcap --interface eth0 --promisc    # Promiscuous mod
talosctl pcap --interface any               # Tüm arayüzler
```

---

## etcd Yönetimi

### `etcd members`
etcd küme üyelerini listele.

```bash
talosctl etcd members
```

---

### `etcd status`
etcd küme üyesi durumunu getir.

```bash
talosctl etcd status
```

---

### `etcd snapshot`
etcd node'unun snapshot'ını al.

```bash
talosctl etcd snapshot ./etcd-backup.snap
```

---

### `etcd alarm`
etcd alarmlarını yönet.

```bash
talosctl etcd alarm list      # Alarmları listele
talosctl etcd alarm disarm    # Alarmları devre dışı bırak
```

---

### `etcd defrag`
etcd veritabanını sıkıştır.

```bash
talosctl etcd defrag
```

---

### `etcd forfeit-leadership`
Node'a etcd küme liderliğini bırakmasını söyle.

```bash
talosctl etcd forfeit-leadership -n 192.168.1.10
```

---

### `etcd leave`
Node'lara etcd kümesinden ayrılmasını söyle.

```bash
talosctl etcd leave -n 192.168.1.10
```

---

### `etcd remove-member`
Node'u etcd kümesinden çıkar.

```bash
talosctl etcd remove-member <member-id>
```

---

### `etcd downgrade`
etcd depolama sistemi düşürme işlemini yönet.

```bash
talosctl etcd downgrade validate --to 3.5
talosctl etcd downgrade enable --to 3.5
talosctl etcd downgrade cancel
```

---

## Yapılandırma Yönetimi (config)

### `config context`
Aktif context'i ayarla.

```bash
talosctl config context my-cluster
```

---

### `config contexts`
Tanımlı context'leri listele.

```bash
talosctl config contexts
```

---

### `config add`
Yeni bir context ekle.

```bash
talosctl config add my-cluster --ca ./ca.crt --crt ./admin.crt --key ./admin.key --endpoints 192.168.1.10
```

---

### `config endpoint`
Mevcut context için endpoint'leri ayarla.

```bash
talosctl config endpoint 192.168.1.10 192.168.1.11
```

---

### `config node`
Mevcut context için node'ları ayarla.

```bash
talosctl config node 192.168.1.20 192.168.1.21
```

---

### `config merge`
Başka bir client yapılandırma dosyasından context'leri birleştir.

```bash
talosctl config merge ./other-talosconfig
```

---

### `config new`
Yeni bir client yapılandırma dosyası oluştur.

```bash
talosctl config new ./new-talosconfig --roles os:admin
```

---

### `config info`
Mevcut context hakkında bilgi göster.

```bash
talosctl config info
```

---

### `config remove`
Context'leri kaldır.

```bash
talosctl config remove my-old-cluster
```

---

## Sertifika ve Anahtar Üretimi (gen)

### `gen config`
Talos kümesi için yapılandırma dosyaları oluştur.

```bash
talosctl gen config my-cluster https://192.168.1.10:6443
talosctl gen config my-cluster https://vip.example.com:6443 \
  --output-dir ./cluster-config \
  --with-secrets ./secrets.yaml
```

---

### `gen secrets`
Sonradan yapılandırma üretmek için kullanılabilecek secrets bundle dosyası oluştur.

```bash
talosctl gen secrets
talosctl gen secrets --output-file ./secrets.yaml
talosctl gen secrets --from-controlplane-config ./controlplane.yaml
```

---

### `gen ca`
Self-signed X.509 sertifika otoritesi oluştur.

```bash
talosctl gen ca --organization "My Org" --hours 87600
```

---

### `gen key`
Ed25519 özel anahtar oluştur.

```bash
talosctl gen key --name my-key
```

---

### `gen keypair`
X.509 Ed25519 anahtar çifti oluştur.

```bash
talosctl gen keypair --ip 192.168.1.10 --organization "My Org"
```

---

### `gen crt`
X.509 Ed25519 sertifika oluştur.

```bash
talosctl gen crt --ca ./ca.crt --ca-key ./ca.key --name admin --hours 8760
```

---

### `gen csr`
Ed25519 özel anahtarı kullanarak CSR oluştur.

```bash
talosctl gen csr --key ./admin.key --ip 192.168.1.10
```

---

### `gen secureboot`
SecureBoot süreci için secret'lar oluştur.

```bash
talosctl gen secureboot uki-signing-cert
talosctl gen secureboot pcr-signing-key
talosctl gen secureboot database
```

---

## Makine Yapılandırması (machineconfig)

### `machineconfig gen` (takma ad: `mc gen`)
Talos kümesi için yapılandırma dosyaları oluştur (`gen config` ile aynı).

```bash
talosctl mc gen my-cluster https://192.168.1.10:6443
```

---

### `machineconfig patch` (takma ad: `mc patch`)
Makine yapılandırmasına patch uygula.

```bash
talosctl mc patch controlplane.yaml --patch @patch.yaml --output patched.yaml
talosctl mc patch controlplane.yaml --patch '[{"op":"add","path":"/machine/network/hostname","value":"node1"}]'
```

---

### `edit`
Varsayılan editörle Talos node makine yapılandırmasını düzenle.

```bash
talosctl edit machineconfig -n 192.168.1.10
talosctl edit machineconfig -n 192.168.1.10 --mode staged
```

---

### `patch`
Talos node makine yapılandırmasına yerel patch uygula.

```bash
talosctl patch machineconfig -n 192.168.1.10 --patch @./my-patch.yaml
talosctl patch mc -n 192.168.1.10 -p '[{"op":"replace","path":"/machine/network/hostname","value":"new-hostname"}]'
```

---

### `validate`
Yapılandırmayı doğrula.

```bash
talosctl validate --config controlplane.yaml --mode metal
talosctl validate -c worker.yaml -m cloud
```

**Modlar:** `metal`, `cloud`, `container`

---

## Image Yönetimi

### `image list`
CRI image'larını listele.

```bash
talosctl image list
talosctl image list --namespace system   # Sistem namespace'i (etcd, kubelet)
```

---

### `image pull`
CRI'a image çek.

```bash
talosctl image pull ghcr.io/siderolabs/installer:v1.12.0
```

---

### `image k8s-bundle`
Talos'un kullandığı varsayılan Kubernetes image'larını listele.

```bash
talosctl image k8s-bundle
```

---

### `image talos-bundle`
Talos için kullanılan varsayılan sistem image'larını ve uzantılarını listele.

```bash
talosctl image talos-bundle
```

---

### `image cache-create`
Image'ların OCI formatında önbelleğini oluştur.

```bash
talosctl image cache-create --images ./images.txt --output-dir ./cache
```

---

### `image cache-serve`
OCI image önbellek dizinini HTTP(S) üzerinden container registry olarak sun.

```bash
talosctl image cache-serve --cache-dir ./cache
```

---

### `image cache-cert-gen`
Image önbelleği ile Talos iletişimini güvence altına almak için TLS sertifikaları oluştur.

```bash
talosctl image cache-cert-gen
```

---

## Yerel Küme Yönetimi (cluster)

Docker veya QEMU tabanlı yerel kümeler için komutlar.

### `cluster create`
Yerel Talos kümesi oluştur.

```bash
talosctl cluster create
talosctl cluster create --name dev-cluster --controlplanes 1 --workers 2
talosctl cluster create --provisioner qemu --cpus 4 --memory 4096
talosctl cluster create --kubernetes-version 1.32.0
talosctl cluster create --with-init-node                 # Bootstrap otomatik
```

**Sık kullanılan bayraklar:**
- `--name` — Küme adı (varsayılan: talos-default)
- `--controlplanes` — Control plane sayısı (varsayılan: 1)
- `--workers` — Worker node sayısı (varsayılan: 1)
- `--provisioner` — `docker` veya `qemu`
- `--kubernetes-version` — Kubernetes sürümü
- `--talos-version` — Talos sürümü
- `--cpus` — CPU sayısı
- `--memory` — Bellek (MB)
- `--disk` — Disk boyutu (MB)
- `--install-image` — Kullanılacak installer image
- `--with-init-node` — Bootstrap'i otomatik yap
- `--cidr` — Node ağı CIDR bloğu
- `--with-kubespan` — KubeSpan'ı etkinleştir
- `--dns-domain` — Kubernetes DNS domain'i

---

### `cluster destroy`
Yerel Talos Kubernetes kümesini sil.

```bash
talosctl cluster destroy
talosctl cluster destroy --name dev-cluster
```

---

### `cluster show`
Yerel küme hakkında bilgi göster.

```bash
talosctl cluster show
talosctl cluster show --name dev-cluster
```

---

## Diğer Komutlar

### `conformance`
Uyumluluk testlerini çalıştır.

```bash
talosctl conformance kubernetes
talosctl conformance kubernetes --mode quick
talosctl conformance kubernetes --mode certified
```

---

### `inject`
Talos API kaynaklarını Kubernetes manifest'lerine enjekte et.

```bash
talosctl inject serviceaccount -f deploy.yaml
```

---

### `completion`
Shell tamamlama kodu çıktısı al.

```bash
talosctl completion bash >> ~/.bashrc
talosctl completion zsh >> ~/.zshrc
talosctl completion fish >> ~/.config/fish/completions/talosctl.fish
```

---

## Pratik Kullanım Örnekleri

### Yeni Küme Kurulumu

```bash
# 1. Secrets oluştur
talosctl gen secrets -o secrets.yaml

# 2. Yapılandırma dosyaları oluştur
talosctl gen config my-cluster https://192.168.1.10:6443 \
  --with-secrets secrets.yaml \
  --output-dir ./cluster-config

# 3. Yapılandırmaları doğrula
talosctl validate -c ./cluster-config/controlplane.yaml -m metal
talosctl validate -c ./cluster-config/worker.yaml -m metal

# 4. Yapılandırmaları uygula
talosctl apply-config -f ./cluster-config/controlplane.yaml \
  -n 192.168.1.10 --insecure

talosctl apply-config -f ./cluster-config/worker.yaml \
  -n 192.168.1.20 --insecure

# 5. Bootstrap
talosctl bootstrap -n 192.168.1.10 \
  --talosconfig ./cluster-config/talosconfig

# 6. Kubeconfig indir
talosctl kubeconfig ./kubeconfig \
  -n 192.168.1.10 \
  --talosconfig ./cluster-config/talosconfig

# 7. Sağlık kontrolü
talosctl health --talosconfig ./cluster-config/talosconfig
```

---

### Yükseltme İş Akışı

```bash
# 1. Mevcut sürümü kontrol et
talosctl version

# 2. Önce etcd snapshot al (yedek)
talosctl etcd snapshot ./etcd-backup.snap -n 192.168.1.10

# 3. Control plane node'larını sırayla yükselt
talosctl upgrade --image ghcr.io/siderolabs/installer:v1.12.1 \
  -n 192.168.1.10 --wait

# 4. Kubernetes'i yükselt
talosctl upgrade-k8s --to 1.32.1
```

---

### Hata Ayıklama

```bash
# Tüm servisleri kontrol et
talosctl service

# Kernel loglarını incele
talosctl dmesg --follow

# Anlık kaynak durumu
talosctl get nodestatus -o yaml

# Ağ durumu
talosctl netstat --listening

# Belirli servis logları
talosctl logs kubelet --tail-lines 200

# Süreç listesi
talosctl processes --sort-by cpu --watch

# Tam destek paketi topla
talosctl support -n 192.168.1.10 --output ./support-bundle.zip
```

---

*Bu döküman `talosctl v1.12.1` için hazırlanmıştır.*
