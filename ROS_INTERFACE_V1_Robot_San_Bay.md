# ROS_INTERFACE_V1 — Robot dẫn đường sân bay

Ngày đề xuất: 11/11/2026.

Đây là hợp đồng giao tiếp ĐỀ XUẤT để phát triển robot và web theo cùng một chuẩn. Các tên /airport/... trong tài liệu do chúng ta quy ước, không phải bằng chứng chúng đã tồn tại trên xe hoặc là tên mặc định của ROS/Nav2. Chưa kiểm tra hoặc biên dịch trên robot của bạn.

## 1. Phạm vi và cách sử dụng

- Một robot, một bản đồ đang hoạt động, một nhiệm vụ dẫn đường tại một thời điểm.
- Hành khách dùng web không cần đăng nhập: chọn đích, bắt đầu, hủy, xem bản đồ/trạng thái và bấm microphone.
- Admin đăng nhập: theo dõi, điều khiển thủ công, thêm/sửa điểm đến và xem cảnh báo.
- Giọng nói được xử lý hoàn toàn trong ROS. Web chỉ yêu cầu bắt đầu nghe và hiển thị dữ liệu ROS cung cấp.
- Phát triển web trên Windows; phần ROS chạy trong Docker ROS 2 Jazzy trên Ubuntu 22.
- Web dùng một gateway để truy cập ROS. Trình duyệt không được cấp một cổng publish/call ROS tùy ý.
- Tên và kiểu dữ liệu dưới đây là phía ROS. URL HTTP/WebSocket của web là cấu hình khác, không thay thế tên ROS.
- Có 11 giao tiếp chính và 4 giao tiếp tùy chọn. Những giao tiếp ROS tự sinh cho action không phải các chức năng mới phải viết riêng.

Bạn có thể giữ nguyên tên và thuật toán bên trong xe. Nếu nguồn hiện tại khác tên hoặc kiểu dữ liệu, thêm ánh xạ/chuyển đổi tại phần kết nối; không đổi hàng loạt cấu hình đang hoạt động chỉ để khớp web.

## 2. Danh sách topic chính

Quy ước chiều “web” dưới đây nghĩa là gateway đứng giữa trình duyệt và ROS.

| Tên đầy đủ | Kiểu dữ liệu | Chiều | Dùng để làm gì |
|---|---|---|---|
| /airport/map | nav_msgs/msg/OccupancyGrid | Robot → web | Bản đồ 2D thực |
| /airport/pose | geometry_msgs/msg/PoseStamped | Robot → web | Vị trí và hướng robot trong hệ map |
| /airport/state | airport_robot_interfaces/msg/RobotState | Robot → web | Trạng thái điều hướng, chế độ điều khiển, đích hiện tại và thông báo |
| /airport/destinations | airport_robot_interfaces/msg/DestinationList | Robot → web và node giọng nói | Danh sách địa điểm dùng chung |
| /airport/voice/state | std_msgs/msg/String | ROS giọng nói → web | Trạng thái IDLE/LISTENING/PROCESSING/SPEAKING/ERROR |
| /airport/alerts | diagnostic_msgs/msg/DiagnosticArray | Các thành phần ROS → web | Cảnh báo/lỗi có tên thành phần và mức độ |
| /airport/cmd_vel_manual | geometry_msgs/msg/TwistStamped | Web admin → bộ phân xử điều khiển robot | Lệnh vận tốc thủ công; không nối trực tiếp với động cơ nếu chưa có phân xử và timeout |

## 3. Danh sách service chính

| Tên đầy đủ | Kiểu dữ liệu | Yêu cầu | Phản hồi |
|---|---|---|---|
| /airport/voice/start | std_srvs/srv/Trigger | Request rỗng | success, message |
| /airport/control/set_manual | std_srvs/srv/SetBool | data=true để xin chuyển MANUAL; false để trở lại AUTO | success, message |
| /airport/destinations/upsert | airport_robot_interfaces/srv/UpsertDestination | Một bản ghi Destination | success, message |

### /airport/voice/start

- Bắt đầu một lượt nghe bằng microphone hiện do chương trình ROS sử dụng.
- Trả lời nhanh sau khi biết có nhận yêu cầu hay không; không giữ service call đến khi hội thoại hoàn tất.
- success=true nghĩa là yêu cầu bắt đầu lượt nghe đã được nhận, không có nghĩa đã hiểu câu nói hoặc đã gửi đích.
- Nếu đang LISTENING/PROCESSING/SPEAKING, từ chối lượt mới với success=false và lý do bận. Không khởi tạo nhiều phiên nghe.
- Node giọng nói tự kết thúc lượt nghe theo chương trình hiện có. Bản v1 chưa cần nút dừng thu âm hoặc service stop riêng.
- Cập nhật /airport/voice/state khi chuyển trạng thái. Khi lỗi, phát thêm /airport/alerts.
- Nếu ROS giọng nói đã quyết định gửi đích, nó là bên gửi goal duy nhất cho câu nói đó; web không gửi thêm goal từ transcript.

### /airport/control/set_manual

- true: khóa việc nhận goal mới, chuyển trạng thái TRANSITION, yêu cầu hủy nhiệm vụ đang chạy, xác minh đầu ra điều khiển tự động đã được ngắt và robot đã dừng theo cơ chế thực tế; sau đó mới chuyển MANUAL và trả success=true.
- Nếu không hoàn tất trong timeout cấu hình: trả success=false; ghi FAULT hoặc trạng thái thực tế, không báo đã chuyển thành công.
- false: ngắt lệnh thủ công, đưa đầu ra về trạng thái dừng, rồi chuyển AUTO. Không tự tiếp tục nhiệm vụ cũ.
- AUTO chỉ có nghĩa cho phép nhận nhiệm vụ tự động; không có nghĩa robot đang chuyển động.
- Chỉ cho admin hợp lệ gọi qua gateway. Dùng một chủ điều khiển thủ công tại một thời điểm.
- Trong MANUAL, action điều hướng từ web hoặc giọng nói đều phải bị từ chối.
- Dừng phần mềm này không được gắn nhãn là nút dừng khẩn cấp phần cứng.

### /airport/destinations/upsert

- id mới: thêm điểm; id đã có: cập nhật.
- Kiểm tra id/tên không rỗng, tọa độ hữu hạn, quaternion hợp lệ, đúng bản đồ hiện tại và frame map.
- Lưu dữ liệu bền vững phía robot, ví dụ YAML, trước khi trả success=true và phát lại DestinationList.
- Không để web và chương trình giọng nói tự giữ hai danh sách độc lập.
- Không sửa đích của nhiệm vụ đang thực hiện một cách âm thầm. Với bản v1, từ chối cập nhật điểm đó khi đang dùng.
- Chưa cần xóa điểm đến vì phạm vi đã chốt chỉ là thêm/sửa.
- Khi khởi động lại phải đọc lại dữ liệu đã lưu. Không tự sinh các cổng bay/tọa độ minh họa.

## 4. Action điều hướng

| Tên action | Kiểu | Bên gọi | Bên cung cấp |
|---|---|---|---|
| /airport/navigate_to_pose | nav2_msgs/action/NavigateToPose | Gateway hoặc chương trình giọng nói | Phần điều phối điều hướng của robot |

Đây là lựa chọn dùng KIỂU action của Nav2 Jazzy cho hợp đồng. Nó không xác nhận xe hiện dùng Nav2.

Nếu xe đã có Nav2, phần điều phối có thể chuyển tiếp đến action hiện có của Nav2, giữ nguyên bộ lập đường và controller. Tên action bên trong phải lấy từ cấu hình thực tế. Nếu xe dùng điều hướng tự viết, cần một adapter cung cấp giao diện tương đương; không cần viết lại thuật toán chỉ để phục vụ web.

### Nội dung gửi và nhận

- Goal có pose kiểu geometry_msgs/PoseStamped. frame_id phải là map; vị trí/hướng lấy từ Destination đã lưu.
- behavior_tree để chuỗi rỗng trong v1; web không được chọn đường dẫn tệp behavior tree tùy ý.
- Feedback chuẩn có current_pose, navigation_time, estimated_time_remaining, number_of_recoveries, distance_remaining.
- Phải dùng trạng thái kết thúc ROS action và result; không coi goal accepted hoặc error_code đơn lẻ là bằng chứng đã đến nơi.
- Bản v1 không bắt buộc đưa ETA hoặc số lần recovery lên màn hình hành khách.
- Một mục tiêu đang hoạt động: từ chối goal mới với lý do bận, không tự ghi đè hành trình.
- Web gateway phải chống gửi trùng khi nhấn hai lần hoặc reconnect. Khi mất kết nối, đọc lại trạng thái thay vì tự gửi lại goal.
- Giọng nói và thao tác nút cùng đi qua /airport/navigate_to_pose để trạng thái được thống nhất.
- Nếu RViz tiếp tục gửi trực tiếp đến một action khác bên trong, thao tác đó có thể bỏ qua phần điều phối. Khi kiểm thử chung với web, cấu hình công cụ gửi đích qua cùng giao diện hoặc chủ động đồng bộ nguồn đó; không mặc định mọi goal từ RViz đã được quản lý.
- Nếu làm proxy action, lưu ánh xạ UUID của goal bên ngoài với UUID goal bên trong để feedback, hủy và kết quả không bị gắn nhầm.

### Hủy chuyến

Dùng chức năng cancel của chính action trên. ROS 2 sinh service hủy:

/airport/navigate_to_pose/_action/cancel_goal

Kiểu: action_msgs/srv/CancelGoal.

Không viết thêm service tự đặt tên /cancel_navigation rồi giả định nó là chuẩn ROS.

Gateway hủy đúng UUID nhiệm vụ hiện tại đã được phép điều khiển. Với goal do giọng nói tạo, có thể dùng UUID được công bố trong /airport/state; không hủy tất cả goal một cách tùy tiện.

Phản hồi đồng ý xử lý yêu cầu cancel chỉ là bước chuyển sang CANCELING. Chỉ báo “Đã hủy” khi nhận terminal state CANCELED. Xác nhận robot đã dừng vật lý còn phụ thuộc bộ điều khiển và dữ liệu thực tế, không suy ra chỉ từ việc gửi cancel.

### Những tên do ROS action tự sinh

| Tên | Loại | Cách dùng |
|---|---|---|
| /airport/navigate_to_pose/_action/send_goal | Service | Action client gửi goal |
| /airport/navigate_to_pose/_action/get_result | Service | Action client lấy kết quả |
| /airport/navigate_to_pose/_action/cancel_goal | Service | Hủy theo UUID |
| /airport/navigate_to_pose/_action/feedback | Topic | Feedback gắn với UUID |
| /airport/navigate_to_pose/_action/status | Topic | action_msgs/msg/GoalStatusArray để quan sát trạng thái |

Dùng thư viện ROS action client/server để quản lý các giao tiếp này, không tự viết thủ công năm giao tiếp độc lập.

## 5. Topic tùy chọn

| Tên | Kiểu | Hiển thị | Khi chưa có |
|---|---|---|---|
| /airport/path | nav_msgs/msg/Path | Đường đi thực tế đang được sử dụng | Ẩn lớp đường đi hoặc báo chưa có, không nối thẳng hai điểm để giả làm đường lập kế hoạch |
| /airport/battery | sensor_msgs/msg/BatteryState | Pin và trạng thái sạc | Hiện chưa có dữ liệu, không tự cho 100% |
| /airport/voice/transcript | std_msgs/msg/String | Câu nói ROS đã nhận dạng | Không cần khu vực câu nhận dạng |
| /airport/voice/response | std_msgs/msg/String | Câu trả lời dạng chữ do ROS tạo | Không cần khu vực câu trả lời |

- BatteryState.percentage theo kiểu chuẩn là tỉ lệ 0..1, ví dụ 0.75 tương ứng 75%. NaN biểu thị không có giá trị; gateway phải chuyển sang null/unknown phù hợp JSON.
- Các trường số pin khác chưa đo được dùng quy ước unknown của message, không nhét giá trị giả.
- Path phải nằm trong map; khi đổi goal, hủy hoặc kết thúc chuyến thì xóa lớp đường đi cũ. Khi chưa có path mới, không giữ path cũ như thể còn hiệu lực.
- Voice transcript/response dùng cho hiển thị. Không dùng chúng như kênh lệnh điều khiển thứ hai.
- Không cần truyền audio, stream microphone hoặc xây nhận dạng/TTS trong web ở phạm vi này.

## 6. Những kiểu dữ liệu tự định nghĩa

Ba message và một service sau là ĐỀ XUẤT của dự án, không có sẵn trong ROS 2. Tạo package airport_robot_interfaces và build/source trong môi trường ROS của các node dùng chúng.

Các tên kiểu đầy đủ phải thống nhất với bảng trên.

### msg/Destination.msg

~~~text
string id
string name
string map_id
geometry_msgs/PoseStamped pose
~~~

- id là mã ổn định, ví dụ gate_a1 chỉ khi địa điểm thật này đã được bạn cấu hình.
- name là tên hiển thị và tên có thể được chương trình giọng nói ánh xạ.
- map_id là mã bản đồ thực tế do dự án đặt; đổi bản đồ vật lý phải đổi hoặc đối chiếu map_id.
- pose.header.frame_id = map; z=0 cho mô hình phẳng.
- pose chứa vị trí x/y theo mét và quaternion hướng cuối cùng, không phải tọa độ pixel.
- Khi giao diện nhập yaw, chuyển yaw sang quaternion; yaw theo radian: qx=qy=0, qz=sin(yaw/2), qw=cos(yaw/2).
- Timestamp pose lưu trong danh sách không được dùng để đánh giá độ mới của robot; khi gửi goal, gateway/node gửi đặt timestamp phù hợp ROS clock hiện tại.

### msg/DestinationList.msg

~~~text
std_msgs/Header header
string map_id
airport_robot_interfaces/Destination[] destinations
~~~

- Đây là toàn bộ danh sách của map_id hiện tại, không phải từng bản ghi bổ sung.
- Danh sách rỗng là hợp lệ: web báo chưa cấu hình điểm đến.
- Một nơi phía robot chịu trách nhiệm lưu và phát danh sách.

### msg/RobotState.msg

~~~text
std_msgs/Header header
string map_id
bool navigation_ready
string control_mode
string navigation_state
string goal_id
bool has_goal
string destination_id
geometry_msgs/PoseStamped goal_pose
string message
~~~

Quy ước:
- control_mode chỉ nhận AUTO, MANUAL, TRANSITION, FAULT.
- navigation_state chỉ nhận IDLE, ACCEPTED, NAVIGATING, CANCELING, SUCCEEDED, CANCELED, FAILED, UNKNOWN.
- Đây là enum bằng chuỗi do dự án quy ước, không phải nguyên xi enum action_msgs.
- EXECUTING của ROS action ánh xạ NAVIGATING; ABORTED ánh xạ FAILED.
- goal_id là UUID public action viết bằng 32 ký tự hex chữ thường, không có dấu gạch; rỗng nếu chưa có goal.
- has_goal cho biết goal_pose/goal_id có ý nghĩa; có thể giữ true ở terminal state để hiển thị chuyến vừa kết thúc. Bận được xác định bằng navigation_state, không chỉ has_goal.
- destination_id có thể rỗng nếu không biết chắc goal ứng với địa điểm nào. Với goal dạng pose, chỉ gán id khi khớp duy nhất bản ghi trong danh sách; không suy đoán tên đích.
- goal_pose và mọi vị trí hiển thị phải trong map. Nếu không xác định được đích, báo chưa có, không dùng pose mặc định (0,0) như đích thật.
- navigation_ready phải dựa trên tình trạng thực: bản đồ, định vị đủ mới, bộ điều hướng sẵn sàng, chế độ phù hợp và không có lỗi chặn. Không đặt true chỉ vì process gateway còn sống.
- message giải thích ngắn gọn trạng thái hiện tại hoặc lỗi. Không đưa dữ liệu bí mật vào đó.
- Khi mất khả năng xác minh nhiệm vụ đang chạy, dùng UNKNOWN và báo lý do; không tự báo IDLE hoặc SUCCEEDED.
- heartbeat /airport/state thể hiện node điều phối còn hoạt động; không tự chứng minh mọi cảm biến đều hoạt động.

### srv/UpsertDestination.srv

~~~text
airport_robot_interfaces/Destination destination
---
bool success
string message
~~~

Đây là đặc tả định dạng, chưa phải package đã được tạo hoặc kiểm thử biên dịch.

## 7. Voice state và cảnh báo

/airport/voice/state dùng std_msgs/msg/String với các giá trị:
- IDLE: sẵn sàng nhận lượt nghe.
- LISTENING: ROS đang thu/nhận tiếng nói.
- PROCESSING: ROS đang xử lý.
- SPEAKING: ROS đang phát phản hồi nếu chương trình hiện có bước này.
- ERROR: có lỗi, xem /airport/alerts.

Node giọng nói phát trạng thái thật, tối thiểu khi đổi trạng thái và thêm heartbeat theo mục 9. Web không tự chuyển sang LISTENING chỉ vì người dùng vừa nhấn nút; trong lúc chờ phản hồi, UI có thể hiện “Đang gửi yêu cầu”.

/airport/alerts dùng DiagnosticArray:
- Mỗi DiagnosticStatus có name ổn định theo thành phần, level, message và hardware_id nếu có.
- Dùng các mức chuẩn OK/WARN/ERROR/STALE; khi lỗi được giải quyết phải phát OK cho cùng name.
- Nếu nhiều node cùng publish, web/gateway quản lý cảnh báo theo khóa thành phần, không xóa cảnh báo của node A khi vừa nhận bản tin node B.
- Thông báo phải giúp người dùng xử lý: chưa định vị, không tìm được đường, hệ giọng nói bận, bộ điều khiển không phản hồi...
- Không bắt buộc truyền toàn bộ /rosout hoặc mọi topic cảm biến ra web.

## 8. Node và frame

Tên node chỉ là gợi ý tổ chức mã. Web phụ thuộc các topic/service/action ở trên, không bắt buộc phụ thuộc tên node nội bộ.

| Node gợi ý | Trách nhiệm |
|---|---|
| /airport/interface_node | Cung cấp action điều phối, RobotState, chuyển chế độ, phân xử lệnh; đọc/chuẩn hóa bản đồ và pose; có thể quản lý danh sách điểm đến trong cùng node để giữ ít tiến trình |
| /airport/voice_node | Chương trình giọng nói đã có: cung cấp voice/start, voice/state, cảnh báo và tùy chọn transcript/response; gửi đích qua cùng action điều phối |
| /airport/web_gateway | Phía server của web: xác thực admin, nhận thao tác, chuyển yêu cầu sang ROS và phát dữ liệu đến trình duyệt |

Không cần đổi tên node giọng nói hiện có thành /airport/voice_node nếu đã hoạt động; chỉ cần cung cấp đúng giao tiếp. Các node SLAM/định vị/Nav2/driver có thể giữ nguyên tên.

Frame quy ước:
- map: bản đồ và tọa độ điểm đến.
- base_link: thân robot, dùng cho lệnh vận tốc thủ công.
- odom: frame nội bộ nếu hệ định vị hiện có sử dụng; không đưa pose odom lên bản đồ map mà bỏ qua phép biến đổi.

Nếu lấy pose từ TF:
- Dùng tf2 để tính pose base_link trong map.
- Các topic TF thông thường là /tf và /tf_static, kiểu tf2_msgs/msg/TFMessage; phải cấu hình đúng namespace/remap thực tế.
- Có thể là chuỗi map → odom → base_link. Không yêu cầu tạo thêm odom nếu hệ hiện có cung cấp một phép biến đổi hợp lệ khác.
- Gateway web chỉ cần /airport/pose, không bắt buộc triển khai xử lý TF trong JavaScript.
- Giữ thời điểm thực của dữ liệu/biến đổi, không liên tục gắn thời gian mới lên pose đã cũ.

## 9. Tần suất, QoS và độ mới đề xuất

Các giá trị dưới đây là cấu hình khởi đầu cho dự án, không phải chuẩn bắt buộc của ROS và chưa được đo trên xe.

| Dữ liệu | Cách phát đề xuất | QoS ở giao diện /airport |
|---|---|---|
| map | Khi có bản đồ hoặc có thay đổi | Reliable, Transient Local, KeepLast 1 |
| destinations | Khi khởi động hoặc thay đổi | Reliable, Transient Local, KeepLast 1 |
| pose | Khoảng 10 Hz nếu định vị cung cấp được | Reliable, Volatile, KeepLast 5 |
| state | Khi đổi trạng thái và heartbeat 2 Hz | Reliable, Volatile, KeepLast 5 |
| voice/state | Khi đổi trạng thái và heartbeat 2 Hz | Reliable, Volatile, KeepLast 5 |
| alerts | Khi thay đổi và cập nhật định kỳ của thành phần | Reliable, Volatile, KeepLast 10 |
| cmd_vel_manual | Lệnh mới khoảng 10–20 Hz trong khi giữ nút | Reliable, Volatile, KeepLast 1 |

- Subscriber phải dùng QoS tương thích. Nếu nguồn robot có QoS khác, relay/adapter chịu trách nhiệm thích ứng; không đổi publisher đang hoạt động một cách mù quáng.
- Không làm hết hạn bản đồ tĩnh chỉ vì nó không publish liên tục. Bản đồ/danh sách được giữ lại không phải tín hiệu robot đang online.
- Đề xuất ban đầu: pose quá 1 giây thì đánh dấu cũ; state/voice heartbeat quá 3 giây thì mất nguồn đó. Điều chỉnh theo tần suất và kiểm thử thực.
- Phân biệt: trình duyệt nối được gateway, gateway thấy nguồn ROS, và dữ liệu từng nguồn có còn mới không.
- Reconnect chỉ lấy lại trạng thái, không phát lại lệnh cũ hoặc tự chuyển sang dữ liệu mô phỏng.

## 10. Lệnh thủ công

/airport/cmd_vel_manual:
- header.frame_id = base_link.
- twist.linear.x: tiến/lùi, đơn vị m/s.
- twist.angular.z: quay trái/phải, đơn vị rad/s.
- Các thành phần còn lại bằng 0 cho robot vi sai phẳng.
- header.stamp lấy từ ROS clock ở gateway, không dùng trực tiếp đồng hồ Windows của trình duyệt.
- Bộ nhận phải kiểm tra chế độ MANUAL, độ mới lệnh và giới hạn vận tốc đã cấu hình theo robot thật.
- Đầu ra cần được phân xử với vận tốc tự động trước khi đi tới driver; không ghép hai nguồn tùy ý vào cùng đầu vào động cơ.
- Gateway chỉ phát khi vẫn nhận thao tác giữ nút mới; không tự lặp vô hạn lệnh cuối sau khi trình duyệt mất kết nối.
- Nhả nút/mất focus/đăng xuất yêu cầu dừng; phía robot và controller đáy phải có timeout dừng độc lập nếu mất luồng lệnh hoặc gateway chết.
- Timeout phải dùng cơ chế phù hợp cả khi ROS clock ngừng cập nhật; bộ đếm thời gian thực/monotonic phía robot thường cần thiết.
- Tốc độ tối đa, timeout và cơ chế xác minh đứng yên là cấu hình phải kiểm thử trên xe trước khi bật điều khiển thật.

## 11. Thứ tự làm để sớm nối được web

1. Chốt kiểu dữ liệu tự định nghĩa, tạo/build airport_robot_interfaces.
2. Cung cấp map, pose và state thật. Web lúc này hiển thị đúng robot.
3. Cung cấp destinations và dịch vụ upsert. Web và giọng nói dùng chung địa điểm.
4. Cung cấp navigate_to_pose, feedback/result và cancel. Kiểm tra một chuyến hoàn chỉnh.
5. Nối voice/start với chương trình đang có; cung cấp voice/state.
6. Hoàn thiện alerts, set_manual và cmd_vel_manual với phân xử/timeout.
7. Thêm path, battery, transcript/response khi nguồn thực đã có.

Không cần làm stream laser, camera, IMU, toàn bộ topic hoặc màn hình chẩn đoán chuyên sâu chỉ để phục vụ web v1.

## 12. Những gì đặc tả này chưa chứng minh

- Chưa xác minh tên ROS đang tồn tại trên xe.
- Chưa biết xe dùng Nav2 hay điều hướng tự viết.
- Chưa xác minh bộ giọng nói đã có cách kích hoạt từ ngoài.
- Chưa có mã adapter, gateway, package interface hoặc kết quả chạy thực.
- Việc cung cấp đúng tên chưa đủ: phải đúng type, ý nghĩa trường dữ liệu, frame, QoS, trạng thái và cách kết nối Docker/DDS.
- Admin login nằm ở backend/gateway; không giải quyết bằng một topic ROS hoặc chỉ ẩn nút ở frontend.

## 13. Tài liệu chuẩn đã đối chiếu

Các tên /airport/... và kiểu airport_robot_interfaces/... là thiết kế đề xuất của dự án. Các kiểu có sẵn được đối chiếu với ROS 2/Nav2:

- [ROS 2 — thiết kế action và tên service/topic tự sinh](https://design.ros2.org/articles/actions.html)
- [Nav2 Jazzy — NavigateToPose.action](https://github.com/ros-navigation/navigation2/blob/jazzy/nav2_msgs/action/NavigateToPose.action)
- [ROS 2 Jazzy — OccupancyGrid.msg](https://github.com/ros2/common_interfaces/blob/jazzy/nav_msgs/msg/OccupancyGrid.msg)
- [ROS 2 Jazzy — Path.msg](https://github.com/ros2/common_interfaces/blob/jazzy/nav_msgs/msg/Path.msg)
- [ROS 2 Jazzy — SetBool.srv](https://github.com/ros2/common_interfaces/blob/jazzy/std_srvs/srv/SetBool.srv)
- [ROS 2 Jazzy — BatteryState.msg](https://github.com/ros2/common_interfaces/blob/jazzy/sensor_msgs/msg/BatteryState.msg)

